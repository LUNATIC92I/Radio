"""Pilote SoapySDR (RTL-SDR, Airspy, SDRplay, HackRF, LimeSDR, PlutoSDR, USRP…).

Le module Python ``SoapySDR`` est fourni par l'installation système de SoapySDR et
de ses modules matériels (voir docs/GUIDE_SDR.md). Ce pilote :
  * n'ouvre que des flux de RÉCEPTION (SOAPY_SDR_RX) ;
  * n'appelle jamais de fonction d'émission, même si le matériel en déclare ;
  * ignore par défaut les périphériques réseau (SoapyRemote) : fonctionnement local.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ..models import DeviceInfo, ReceiverConfig
from .base import Receiver, ReceiverError

log = logging.getLogger(__name__)

NETWORK_DRIVERS = {"remote", "soapyremote", "plutosdr_net", "uhd_net"}


def _import_soapy() -> Any | None:
    try:
        import SoapySDR  # type: ignore

        return SoapySDR
    except Exception:  # noqa: BLE001 — ImportError ou bibliothèque native absente
        return None


def soapy_available() -> bool:
    return _import_soapy() is not None


def _is_network(kw: dict[str, str]) -> bool:
    drv = kw.get("driver", "").lower()
    return drv in NETWORK_DRIVERS or "remote" in kw or kw.get("hostname") is not None or (
        "addr" in kw and not kw.get("addr", "").startswith("usb")
    )


def _device_id(kw: dict[str, str]) -> str:
    drv = kw.get("driver", "?")
    ser = kw.get("serial") or kw.get("label") or kw.get("addr") or "0"
    return f"soapy:{drv}:{ser}"


def describe_device(sdr_mod: Any, kw: dict[str, str], probe: bool = True) -> DeviceInfo:
    info = DeviceInfo(
        device_id=_device_id(kw),
        driver=kw.get("driver", "?"),
        label=kw.get("label", kw.get("driver", "Récepteur SoapySDR")),
        manufacturer=kw.get("manufacturer", "inconnu"),
        model=kw.get("product", kw.get("driver", "inconnu")),
        serial=kw.get("serial", ""),
        backend="soapy",
        connected=True,
        driver_available=True,
        args=dict(kw),
    )
    if not probe:
        return info
    dev = None
    try:
        dev = sdr_mod.Device(kw)
        rx = sdr_mod.SOAPY_SDR_RX
        info.rx_channels = int(dev.getNumChannels(rx))
        try:
            info.tx_declared = int(dev.getNumChannels(sdr_mod.SOAPY_SDR_TX)) > 0
        except Exception:  # noqa: BLE001
            info.tx_declared = False
        hw = dict(dev.getHardwareInfo()) if hasattr(dev, "getHardwareInfo") else {}
        info.model = hw.get("product", dev.getHardwareKey() or info.model)
        info.manufacturer = hw.get("manufacturer", info.manufacturer)
        info.freq_ranges_hz = [(float(r.minimum()), float(r.maximum())) for r in dev.getFrequencyRange(rx, 0)]
        rates = list(dev.listSampleRates(rx, 0))
        if not rates and hasattr(dev, "getSampleRateRange"):
            rates = [v for r in dev.getSampleRateRange(rx, 0) for v in (r.minimum(), r.maximum())]
        info.sample_rates_hz = sorted(float(r) for r in rates)
        g = dev.getGainRange(rx, 0)
        info.gain_range_db = (float(g.minimum()), float(g.maximum()))
        info.antennas = list(dev.listAntennas(rx, 0))
        if info.tx_declared:
            info.notes.append("Le matériel déclare une capacité d'émission : elle n'est JAMAIS utilisée.")
    except Exception as exc:  # noqa: BLE001
        info.notes.append(f"Interrogation des capacités impossible : {exc}")
    finally:
        if dev is not None:
            try:
                sdr_mod.Device.unmake(dev)
            except Exception:  # noqa: BLE001
                pass
    return info


def enumerate_soapy(allow_network: bool = False, probe: bool = True) -> list[DeviceInfo]:
    mod = _import_soapy()
    if mod is None:
        return []
    out = []
    try:
        results = mod.Device.enumerate()
    except Exception as exc:  # noqa: BLE001
        log.warning("Énumération SoapySDR impossible : %s", exc)
        return []
    for k in results:
        kw = {str(a): str(b) for a, b in dict(k).items()}
        if _is_network(kw) and not allow_network:
            log.info("Périphérique réseau ignoré (mode local) : %s", kw)
            continue
        out.append(describe_device(mod, kw, probe))
    return out


class SoapyReceiver(Receiver):
    def __init__(self, info: DeviceInfo, read_timeout_us: int = 500_000):
        super().__init__(info)
        self._mod = _import_soapy()
        if self._mod is None:
            raise ReceiverError("Module Python SoapySDR introuvable : installez SoapySDR (voir GUIDE_SDR).")
        self._dev = None
        self._stream = None
        self.read_timeout_us = read_timeout_us
        self.overflows = 0

    def open(self) -> None:
        m = self._mod
        try:
            self._dev = m.Device(self.info.args)
            self._apply(self.config)
            self._stream = self._dev.setupStream(m.SOAPY_SDR_RX, m.SOAPY_SDR_CF32, [0])
            self._dev.activateStream(self._stream)
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise ReceiverError(f"Ouverture du récepteur impossible : {exc}") from exc
        self._open = True

    def close(self) -> None:
        m = self._mod
        if self._dev is not None:
            try:
                if self._stream is not None:
                    self._dev.deactivateStream(self._stream)
                    self._dev.closeStream(self._stream)
            except Exception:  # noqa: BLE001
                pass
            try:
                m.Device.unmake(self._dev)
            except Exception:  # noqa: BLE001
                pass
        self._dev = None
        self._stream = None
        self._open = False

    def _apply(self, cfg: ReceiverConfig) -> ReceiverConfig:
        applied = ReceiverConfig(**cfg.to_dict())
        if self._dev is None:
            return applied
        m, d, rx = self._mod, self._dev, self._mod.SOAPY_SDR_RX
        d.setSampleRate(rx, 0, float(cfg.sample_rate_hz))
        if cfg.bandwidth_hz:
            try:
                d.setBandwidth(rx, 0, float(cfg.bandwidth_hz))
            except Exception as exc:  # noqa: BLE001
                log.info("Filtre analogique non réglable : %s", exc)
        if cfg.antenna:
            d.setAntenna(rx, 0, cfg.antenna)
        if cfg.ppm_correction:
            try:
                d.setFrequencyCorrection(rx, 0, float(cfg.ppm_correction))
            except Exception as exc:  # noqa: BLE001
                log.info("Correction ppm non prise en charge : %s", exc)
        if cfg.gain_db is None:
            try:
                d.setGainMode(rx, 0, True)
            except Exception:  # noqa: BLE001
                applied.gain_db = None
        else:
            try:
                d.setGainMode(rx, 0, False)
            except Exception:  # noqa: BLE001
                pass
            d.setGain(rx, 0, float(self.clamp_gain(cfg.gain_db)))
            applied.gain_db = float(d.getGain(rx, 0))
        d.setFrequency(rx, 0, float(cfg.center_freq_hz))
        applied.center_freq_hz = float(d.getFrequency(rx, 0))
        applied.sample_rate_hz = float(d.getSampleRate(rx, 0))
        del m
        return applied

    def read(self, n: int) -> np.ndarray:
        if not self._open:
            raise ReceiverError("Récepteur non ouvert.")
        buf = np.empty(n, np.complex64)
        got = 0
        with self._lock:
            while got < n:
                view = buf[got:]
                sr = self._dev.readStream(self._stream, [view], len(view), timeoutUs=self.read_timeout_us)
                ret = int(sr.ret)
                if ret > 0:
                    got += ret
                elif ret == getattr(self._mod, "SOAPY_SDR_OVERFLOW", -4):
                    self.overflows += 1
                elif ret == getattr(self._mod, "SOAPY_SDR_TIMEOUT", -1):
                    raise ReceiverError("Délai de lecture dépassé : vérifiez la connexion USB du récepteur.")
                else:
                    raise ReceiverError(f"Erreur de flux SoapySDR (code {ret}).")
        return buf
