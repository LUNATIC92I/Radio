"""Interface commune des récepteurs (RÉCEPTION SEULE).

Aucune classe de pilote n'expose de méthode d'émission. Les équipements dont le
matériel déclare une capacité d'émission (HackRF, PlutoSDR, LimeSDR, USRP…) sont
ouverts exclusivement en réception.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod

import numpy as np

from ..models import DeviceInfo, ReceiverConfig


class ReceiverError(RuntimeError):
    """Erreur matérielle ou de configuration, avec message compréhensible."""


class Receiver(ABC):
    def __init__(self, info: DeviceInfo):
        self.info = info
        self.config = ReceiverConfig()
        self._lock = threading.RLock()
        self._open = False

    @property
    def simulated(self) -> bool:
        return self.info.simulated

    @property
    def is_open(self) -> bool:
        return self._open

    def validate_config(self, cfg: ReceiverConfig) -> tuple[list[str], list[str]]:
        """Retourne (erreurs bloquantes, avertissements) selon les capacités déclarées."""
        errors: list[str] = []
        warnings: list[str] = []
        info = self.info
        if info.freq_ranges_hz and not info.supports_frequency(cfg.center_freq_hz):
            errors.append(
                f"Fréquence {cfg.center_freq_hz / 1e6:.4f} MHz hors de la plage du récepteur ({info.frequency_summary()})."
            )
        else:
            for edge in (cfg.center_freq_hz - cfg.sample_rate_hz / 2, cfg.center_freq_hz + cfg.sample_rate_hz / 2):
                if info.freq_ranges_hz and not info.supports_frequency(edge):
                    warnings.append("Une partie de la bande observée dépasse la plage déclarée du récepteur.")
                    break
        if info.sample_rates_hz:
            lo, hi = min(info.sample_rates_hz), max(info.sample_rates_hz)
            if not lo <= cfg.sample_rate_hz <= hi:
                errors.append(f"Fréquence d'échantillonnage {cfg.sample_rate_hz / 1e3:.0f} kS/s hors plage "
                              f"({lo / 1e3:.0f}–{hi / 1e3:.0f} kS/s).")
        if cfg.gain_db is not None:
            g0, g1 = info.gain_range_db
            if g1 > g0 and not g0 <= cfg.gain_db <= g1:
                warnings.append(f"Gain {cfg.gain_db:.1f} dB ramené dans la plage {g0:.0f}–{g1:.0f} dB.")
        if cfg.antenna and info.antennas and cfg.antenna not in info.antennas:
            errors.append(f"Antenne « {cfg.antenna} » inconnue ({', '.join(info.antennas)}).")
        return errors, warnings

    def clamp_gain(self, gain: float | None) -> float | None:
        if gain is None:
            return None
        g0, g1 = self.info.gain_range_db
        return float(min(max(gain, g0), g1)) if g1 > g0 else float(gain)

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def _apply(self, cfg: ReceiverConfig) -> ReceiverConfig: ...

    @abstractmethod
    def read(self, n: int) -> np.ndarray:
        """Lit `n` échantillons IQ complex64 normalisés (pleine échelle = ±1)."""

    def configure(self, cfg: ReceiverConfig) -> ReceiverConfig:
        errors, _ = self.validate_config(cfg)
        if errors:
            raise ReceiverError(" ".join(errors))
        with self._lock:
            applied = self._apply(cfg)
            self.config = applied
            return applied

    def __enter__(self) -> Receiver:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
