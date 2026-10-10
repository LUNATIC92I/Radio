"""« Récepteur » de rejeu : lit une capture IQ enregistrée (SigMF ou brute).

La fréquence centrale et la fréquence d'échantillonnage sont imposées par le
fichier ; elles ne peuvent pas être modifiées (le rejeu ne fait pas de réception).
"""

from __future__ import annotations

import time

import numpy as np

from ..iq_io import IQCapture
from ..models import DeviceInfo, ReceiverConfig
from .base import Receiver, ReceiverError


class IQFileReceiver(Receiver):
    def __init__(self, capture: IQCapture, loop: bool = True, realtime: bool = True):
        info = DeviceInfo(
            device_id=f"iqfile:{capture.data_path.name}",
            driver="iqfile",
            label=f"Rejeu IQ : {capture.data_path.name}",
            manufacturer="Fichier",
            model=capture.datatype,
            backend="iqfile",
            freq_ranges_hz=[(capture.center_freq, capture.center_freq)],
            sample_rates_hz=[capture.sample_rate],
            connected=True,
            driver_available=True,
            simulated=capture.simulated,
            notes=["Rejeu d'enregistrement : fréquence et débit fixés par le fichier."],
        )
        super().__init__(info)
        self.capture = capture
        self.loop = loop
        self.realtime = realtime
        self.pos = 0
        self.config = ReceiverConfig(capture.center_freq, capture.sample_rate, None)
        self._t_last = 0.0

    def validate_config(self, cfg: ReceiverConfig) -> tuple[list[str], list[str]]:
        warnings = []
        if abs(cfg.center_freq_hz - self.capture.center_freq) > 1 or abs(cfg.sample_rate_hz - self.capture.sample_rate) > 1:
            warnings.append("Rejeu : fréquence/débit imposés par le fichier, paramètres ignorés.")
        return [], warnings

    def open(self) -> None:
        if self.capture.num_samples == 0:
            raise ReceiverError("Capture IQ vide.")
        self.pos = 0
        self._open = True
        self._t_last = time.monotonic()

    def close(self) -> None:
        self._open = False

    def _apply(self, cfg: ReceiverConfig) -> ReceiverConfig:
        return ReceiverConfig(self.capture.center_freq, self.capture.sample_rate, None)

    def read(self, n: int) -> np.ndarray:
        if not self._open:
            raise ReceiverError("Rejeu non démarré.")
        out = []
        need = n
        total = self.capture.num_samples
        while need > 0:
            if self.pos >= total:
                if not self.loop:
                    break
                self.pos = 0
            chunk = self.capture.read(self.pos, need)
            self.pos += len(chunk)
            need -= len(chunk)
            out.append(chunk)
        x = np.concatenate(out) if out else np.zeros(0, np.complex64)
        if len(x) < n:
            raise EOFError("Fin de la capture IQ")
        if self.realtime:
            due = n / self.capture.sample_rate
            el = time.monotonic() - self._t_last
            if el < due:
                time.sleep(due - el)
            self._t_last = time.monotonic()
        return x
