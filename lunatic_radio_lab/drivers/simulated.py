"""Récepteur simulé : aucun matériel, aucune émission. Toutes les données sont marquées SIMULÉES.

Modélise un récepteur à ADC 12 bits : le gain amplifie le signal
d'antenne simulé, un bruit propre (ADC) est ajouté, puis le signal est quantifié et
écrêté à la pleine échelle — ce qui permet de tester l'indicateur de saturation.
"""

from __future__ import annotations

import time

import numpy as np

from ..dsp.synth import Scenario, SignalGenerator, preset_scenarios
from ..models import DeviceInfo, ReceiverConfig
from .base import Receiver, ReceiverError

SIM_DEVICE_ID = "sim:0"
REFERENCE_GAIN_DB = 30.0  # gain auquel les niveaux du scénario sont « tels quels »


def simulated_device_info() -> DeviceInfo:
    return DeviceInfo(
        device_id=SIM_DEVICE_ID,
        driver="simulation",
        label="Récepteur simulé LUNATIC SIM-1",
        manufacturer="Lunatic Radio Lab (simulation)",
        model="SIM-1 (ADC 12 bits simulé)",
        serial="SIMULATION",
        backend="simulation",
        freq_ranges_hz=[(24e6, 1_766e6)],
        sample_rates_hz=[62_500.0, 3_200_000.0],
        gain_range_db=(0.0, 60.0),
        antennas=["RX"],
        adc_bits=12,
        connected=True,
        driver_available=True,
        simulated=True,
        notes=["Aucune réception réelle : signaux synthétiques générés localement."],
    )


class SimulatedReceiver(Receiver):
    def __init__(self, scenario: Scenario | None = None, realtime: bool = True, adc_noise_dbfs: float = -75.0,
                 adc_bits: int | None = 12):
        super().__init__(simulated_device_info())
        self.scenario = scenario or preset_scenarios()["intermittent"]
        self.realtime = realtime
        self.adc_noise_dbfs = adc_noise_dbfs
        self.adc_bits = adc_bits
        self._gen: SignalGenerator | None = None
        self._rng = np.random.default_rng(99)
        self._t_last = 0.0

    def set_scenario(self, scenario: Scenario) -> None:
        with self._lock:
            self.scenario = scenario
            self._gen = SignalGenerator(scenario, self.config.sample_rate_hz)

    def open(self) -> None:
        self._gen = SignalGenerator(self.scenario, self.config.sample_rate_hz)
        self._open = True
        self._t_last = time.monotonic()

    def close(self) -> None:
        self._open = False

    def _apply(self, cfg: ReceiverConfig) -> ReceiverConfig:
        applied = ReceiverConfig(**cfg.to_dict())
        applied.gain_db = self.clamp_gain(cfg.gain_db)
        if self._gen is not None:
            self._gen.set_sample_rate(cfg.sample_rate_hz)
        return applied

    def read(self, n: int) -> np.ndarray:
        if not self._open or self._gen is None:
            raise ReceiverError("Récepteur simulé non ouvert.")
        with self._lock:
            cfg = self.config
            # correction ppm simulée : décale la fréquence perçue
            fc = cfg.center_freq_hz * (1.0 + cfg.ppm_correction * 1e-6)
            x = self._gen.generate(n, fc).astype(np.complex128)
            gain = REFERENCE_GAIN_DB if cfg.gain_db is None else cfg.gain_db
            x *= 10 ** ((gain - REFERENCE_GAIN_DB) / 20)
            s = np.sqrt(10 ** (self.adc_noise_dbfs / 10) / 2)
            x += s * (self._rng.standard_normal(n) + 1j * self._rng.standard_normal(n))
            if self.adc_bits:
                q = 2 ** (self.adc_bits - 1)
                x = (np.round(x.real * q) + 1j * np.round(x.imag * q)) / q
            x = np.clip(x.real, -1, 1) + 1j * np.clip(x.imag, -1, 1)
        if self.realtime:
            # cadence temps réel approximative
            due = n / cfg.sample_rate_hz
            elapsed = time.monotonic() - self._t_last
            if elapsed < due:
                time.sleep(due - elapsed)
            self._t_last = time.monotonic()
        return x.astype(np.complex64)
