"""Détection passive des récepteurs SDR connectés en USB (identifiants VID:PID).

Permet d'indiquer « matériel branché mais pilote SDR absent ». Lecture seule de
/sys/bus/usb/devices (Linux) ; sous Windows/macOS, ou si pyusb est installé, on
utilise pyusb s'il est disponible. Aucune commande n'est envoyée au matériel.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models import DeviceInfo

log = logging.getLogger(__name__)

# (vid, pid) -> (fabricant, modèle, plage de fréquences déclarée par le constructeur, tx déclarée)
KNOWN_SDR: dict[tuple[int, int], tuple[str, str, list[tuple[float, float]], bool]] = {
    (0x0BDA, 0x2838): ("Realtek / générique", "RTL2832U (RTL-SDR)", [(24e6, 1_766e6)], False),
    (0x0BDA, 0x2832): ("Realtek / générique", "RTL2832U (RTL-SDR)", [(24e6, 1_766e6)], False),
    (0x1D50, 0x6089): ("Great Scott Gadgets", "HackRF One", [(1e6, 6_000e6)], True),
    (0x1D50, 0x60A1): ("Airspy", "Airspy R2 / Mini", [(24e6, 1_800e6)], False),
    (0x03EB, 0x800C): ("Airspy", "Airspy HF+", [(0.5e3, 31e6), (60e6, 260e6)], False),
    (0x1DF7, 0x2500): ("SDRplay", "RSP1", [(10e3, 2_000e6)], False),
    (0x1DF7, 0x3000): ("SDRplay", "RSP1A", [(1e3, 2_000e6)], False),
    (0x1DF7, 0x3010): ("SDRplay", "RSP2", [(1e3, 2_000e6)], False),
    (0x1DF7, 0x3020): ("SDRplay", "RSPduo", [(1e3, 2_000e6)], False),
    (0x1DF7, 0x3050): ("SDRplay", "RSPdx", [(1e3, 2_000e6)], False),
    (0x1D50, 0x6108): ("Lime Microsystems", "LimeSDR", [(100e3, 3_800e6)], True),
    (0x0403, 0x601F): ("Lime Microsystems", "LimeSDR Mini", [(10e6, 3_500e6)], True),
    (0x0456, 0xB673): ("Analog Devices", "ADALM-PLUTO", [(325e6, 3_800e6)], True),
    (0x2500, 0x0020): ("Ettus Research", "USRP B200/B210", [(70e6, 6_000e6)], True),
    (0x04D8, 0xFB56): ("FUNcube", "FUNcube Dongle Pro", [(64e6, 1_700e6)], False),
    (0x04D8, 0xFB31): ("FUNcube", "FUNcube Dongle Pro+", [(150e3, 1_900e6)], False),
}


def _scan_sysfs() -> list[tuple[int, int, str, str]]:
    base = Path("/sys/bus/usb/devices")
    out = []
    if not base.is_dir():
        return out
    for d in base.iterdir():
        try:
            vid = int((d / "idVendor").read_text().strip(), 16)
            pid = int((d / "idProduct").read_text().strip(), 16)
        except (OSError, ValueError):
            continue
        serial = ""
        try:
            serial = (d / "serial").read_text().strip()
        except OSError:
            pass
        out.append((vid, pid, serial, d.name))
    return out


def _scan_pyusb() -> list[tuple[int, int, str, str]]:
    try:
        import usb.core  # type: ignore
    except Exception:  # noqa: BLE001
        return []
    out = []
    try:
        for dev in usb.core.find(find_all=True):
            out.append((int(dev.idVendor), int(dev.idProduct), "", f"bus{dev.bus}-{dev.address}"))
    except Exception as exc:  # noqa: BLE001
        log.info("Scan pyusb impossible : %s", exc)
    return out


def scan_usb_sdr() -> list[DeviceInfo]:
    found = _scan_sysfs() or _scan_pyusb()
    out = []
    for vid, pid, serial, loc in found:
        k = (vid, pid)
        if k not in KNOWN_SDR:
            continue
        man, model, ranges, tx = KNOWN_SDR[k]
        info = DeviceInfo(
            device_id=f"usb:{vid:04x}:{pid:04x}:{serial or loc}",
            driver="usb",
            label=f"{model} (USB {vid:04x}:{pid:04x})",
            manufacturer=man,
            model=model,
            serial=serial,
            backend="usb",
            freq_ranges_hz=ranges,
            connected=True,
            driver_available=False,
            tx_declared=tx,
            notes=["Plage indicative du constructeur ; installez le module SoapySDR correspondant pour l'utiliser."],
        )
        if tx:
            info.notes.append("Le matériel peut émettre : le logiciel ne l'utilise QU'EN RÉCEPTION.")
        out.append(info)
    return out
