"""Pilote GNU Radio (gr-osmosdr) — chaîne de RÉCEPTION uniquement.

Graphe : osmosdr.source → bloc Python (tampon circulaire) ; aucun bloc « sink »
matériel n'est instancié. Requiert GNU Radio ≥ 3.9 et gr-osmosdr installés par le
gestionnaire de paquets du système (voir docs/GUIDE_SDR.md).

Statut : implémentation fonctionnelle mais NON VALIDÉE sur matériel réel dans
cette version (voir docs/BILAN_FONCTIONNALITES.md). SoapySDR est recommandé.
"""

from __future__ import annotations

import collections
import logging
import threading
from typing import Any

import numpy as np

from ..models import DeviceInfo, ReceiverConfig
from .base import Receiver, ReceiverError

log = logging.getLogger(__name__)


def _import_gr() -> tuple[Any, Any, Any] | None:
    try:
        import osmosdr  # type: ignore
        from gnuradio import gr  # type: ignore

        return gr, osmosdr, None
    except Exception:  # noqa: BLE001
        return None


def gnuradio_available() -> bool:
    return _import_gr() is not None


def enumerate_gnuradio() -> list[DeviceInfo]:
    mods = _import_gr()
    if mods is None:
        return []
    _, osmosdr, _ = mods
    out: list[DeviceInfo] = []
    try:
        devs = osmosdr.device.find()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        log.info("Énumération gr-osmosdr indisponible : %s", exc)
        return out
    for i, d in enumerate(devs):
        args = str(d.to_string()) if hasattr(d, "to_string") else str(d)
        kv = dict(part.split("=", 1) for part in args.split(",") if "=" in part)
        if kv.get("remote") or kv.get("rtl_tcp") or kv.get("soapy", "").startswith("remote"):
            continue  # fonctionnement local par défaut
        out.append(
            DeviceInfo(
                device_id=f"gnuradio:{i}:{args}",
                driver="osmosdr",
                label=kv.get("label", f"gr-osmosdr #{i}"),
                model=args,
                backend="gnuradio",
                connected=True,
                driver_available=True,
                args={"osmosdr_args": args},
                notes=["Capacités détaillées non interrogées via gr-osmosdr ; vérifiez la documentation du matériel."],
            )
        )
    return out


class GnuRadioReceiver(Receiver):
    def __init__(self, info: DeviceInfo, buffer_seconds: float = 2.0):
        super().__init__(info)
        mods = _import_gr()
        if mods is None:
            raise ReceiverError("GNU Radio / gr-osmosdr introuvables.")
        self._gr, self._osmosdr, _ = mods
        self._tb = None
        self._src = None
        self._buf: collections.deque[np.ndarray] = collections.deque()
        self._buffered = 0
        self._cond = threading.Condition()
        self.buffer_seconds = buffer_seconds
        self.dropped = 0

    def _make_sink(self) -> Any:
        gr = self._gr
        owner = self

        class _Sink(gr.sync_block):  # type: ignore[misc, name-defined]
            def __init__(self) -> None:
                gr.sync_block.__init__(self, name="lrl_sink", in_sig=[np.complex64], out_sig=None)

            def work(self, input_items, output_items):  # noqa: ANN001
                owner._push(np.array(input_items[0], copy=True))
                return len(input_items[0])

        return _Sink()

    def _push(self, x: np.ndarray) -> None:
        with self._cond:
            self._buf.append(x)
            self._buffered += len(x)
            limit = int(self.buffer_seconds * self.config.sample_rate_hz)
            while self._buffered > limit and self._buf:
                self._buffered -= len(self._buf.popleft())
                self.dropped += 1
            self._cond.notify_all()

    def open(self) -> None:
        gr, osmosdr = self._gr, self._osmosdr
        try:
            self._tb = gr.top_block("lrl_rx")
            self._src = osmosdr.source(args=self.info.args.get("osmosdr_args", ""))
            self._apply(self.config)
            self._tb.connect(self._src, self._make_sink())
            self._tb.start()
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise ReceiverError(f"Démarrage du graphe GNU Radio impossible : {exc}") from exc
        self._open = True

    def close(self) -> None:
        if self._tb is not None:
            try:
                self._tb.stop()
                self._tb.wait()
            except Exception:  # noqa: BLE001
                pass
        self._tb = None
        self._src = None
        self._open = False

    def _apply(self, cfg: ReceiverConfig) -> ReceiverConfig:
        applied = ReceiverConfig(**cfg.to_dict())
        s = self._src
        if s is None:
            return applied
        applied.sample_rate_hz = float(s.set_sample_rate(cfg.sample_rate_hz))
        applied.center_freq_hz = float(s.set_center_freq(cfg.center_freq_hz, 0))
        if cfg.ppm_correction:
            s.set_freq_corr(cfg.ppm_correction, 0)
        if cfg.gain_db is None:
            s.set_gain_mode(True, 0)
        else:
            s.set_gain_mode(False, 0)
            applied.gain_db = float(s.set_gain(cfg.gain_db, 0))
        if cfg.bandwidth_hz:
            s.set_bandwidth(cfg.bandwidth_hz, 0)
        if cfg.antenna:
            s.set_antenna(cfg.antenna, 0)
        with self._cond:
            self._buf.clear()
            self._buffered = 0
        return applied

    def read(self, n: int) -> np.ndarray:
        if not self._open:
            raise ReceiverError("Récepteur non ouvert.")
        with self._cond:
            ok = self._cond.wait_for(lambda: self._buffered >= n, timeout=2.0)
            if not ok:
                raise ReceiverError("Aucun échantillon reçu de GNU Radio (délai dépassé).")
            parts, got = [], 0
            while got < n:
                blk = self._buf.popleft()
                take = min(len(blk), n - got)
                parts.append(blk[:take])
                if take < len(blk):
                    self._buf.appendleft(blk[take:])
                got += take
            self._buffered -= n
        return np.concatenate(parts).astype(np.complex64)
