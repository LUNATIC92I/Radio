"""Découverte des équipements et création des récepteurs."""

from __future__ import annotations

import logging

from ..models import DeviceInfo
from .base import Receiver, ReceiverError
from .gnuradio_driver import GnuRadioReceiver, enumerate_gnuradio, gnuradio_available
from .simulated import SimulatedReceiver, simulated_device_info
from .soapy_driver import SoapyReceiver, enumerate_soapy, soapy_available
from .usb_scan import scan_usb_sdr

log = logging.getLogger(__name__)

# correspondance modèle USB -> nom de module SoapySDR (pour éviter les doublons)
SOAPY_DRIVER_KEYS = {
    "RTL2832U": "rtlsdr", "HackRF": "hackrf", "Airspy HF": "airspyhf", "Airspy R2": "airspy",
    "RSP": "sdrplay", "LimeSDR": "lime", "ADALM-PLUTO": "plutosdr", "USRP": "uhd", "FUNcube": "fcd",
}


def backend_status() -> dict[str, bool]:
    return {"simulation": True, "soapysdr": soapy_available(), "gnuradio": gnuradio_available()}


def discover_devices(include_simulation: bool = True, allow_network: bool = False, probe: bool = True) -> list[DeviceInfo]:
    """Liste les récepteurs : SoapySDR, GNU Radio, USB (sans pilote) et simulation.

    Un matériel vu en USB et aussi par SoapySDR n'est listé qu'une fois (entrée SoapySDR).
    """
    devices: list[DeviceInfo] = []
    soapy = enumerate_soapy(allow_network=allow_network, probe=probe)
    devices.extend(soapy)
    devices.extend(enumerate_gnuradio())
    usb = scan_usb_sdr()
    soapy_serials = {d.serial for d in soapy if d.serial}
    remaining = [d.driver.lower() for d in soapy]
    for u in usb:
        if u.serial and u.serial in soapy_serials:
            continue
        key = next((v for k, v in SOAPY_DRIVER_KEYS.items() if k.lower() in u.model.lower()), None)
        if key and key in remaining:
            remaining.remove(key)  # déjà listé via SoapySDR
            continue
        devices.append(u)
    if include_simulation:
        devices.append(simulated_device_info())
    return devices


def create_receiver(info: DeviceInfo) -> Receiver:
    if info.backend == "simulation":
        return SimulatedReceiver()
    if info.backend == "soapy":
        return SoapyReceiver(info)
    if info.backend == "gnuradio":
        return GnuRadioReceiver(info)
    if info.backend == "usb":
        raise ReceiverError(
            f"{info.model} est branché mais aucun pilote SDR n'est disponible. "
            "Installez SoapySDR et le module correspondant (voir docs/GUIDE_SDR.md)."
        )
    raise ReceiverError(f"Type de récepteur non pris en charge : {info.backend}")
