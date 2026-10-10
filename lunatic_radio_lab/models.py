"""Structures de données partagées entre les couches (pilotes, DSP, stockage, GUI)."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

# Unité de puissance par défaut : dBFS relatif (non calibré). Une puissance absolue
# (dBm) n'est affichée que si l'utilisateur a saisi un décalage d'étalonnage.
POWER_UNIT_RELATIVE = "dBFS"


@dataclass
class DeviceInfo:
    """Description d'un récepteur détecté, telle que déclarée par son pilote."""

    device_id: str
    driver: str
    label: str
    manufacturer: str = "inconnu"
    model: str = "inconnu"
    serial: str = ""
    backend: str = "simulation"  # simulation | soapy | gnuradio | iqfile | usb
    freq_ranges_hz: list[tuple[float, float]] = field(default_factory=list)
    sample_rates_hz: list[float] = field(default_factory=list)
    gain_range_db: tuple[float, float] = (0.0, 0.0)
    antennas: list[str] = field(default_factory=list)
    adc_bits: int | None = None
    rx_channels: int = 1
    tx_declared: bool = False  # capacité déclarée par le matériel ; jamais utilisée
    connected: bool = False
    driver_available: bool = False
    simulated: bool = False
    args: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def supports_frequency(self, freq_hz: float) -> bool:
        if not self.freq_ranges_hz:
            return False
        return any(lo <= freq_hz <= hi for lo, hi in self.freq_ranges_hz)

    def frequency_summary(self) -> str:
        if not self.freq_ranges_hz:
            return "non déclarée"
        return ", ".join(f"{lo / 1e6:.3f}–{hi / 1e6:.3f} MHz" for lo, hi in self.freq_ranges_hz)

    @property
    def status_text(self) -> str:
        if self.simulated:
            return "Simulation (aucun matériel)"
        if self.connected and self.driver_available:
            return "Connecté — pilote disponible"
        if self.connected:
            return "Connecté (USB) — pilote SDR absent"
        return "Non connecté"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReceiverConfig:
    center_freq_hz: float = 446.1e6
    sample_rate_hz: float = 250_000.0
    gain_db: float | None = 30.0  # None => AGC automatique si disponible
    bandwidth_hz: float | None = None
    ppm_correction: float = 0.0
    antenna: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpectrumFrame:
    """Une trame de spectre moyennée."""

    freqs_hz: np.ndarray
    power_dbfs: np.ndarray  # dBFS par case FFT (normalisé : sinusoïde pleine échelle = 0 dBFS)
    timestamp: float
    center_freq_hz: float
    sample_rate_hz: float
    fft_size: int
    averages: int
    rbw_hz: float  # largeur de bande de résolution (ENBW de la fenêtre)
    enbw_bins: float
    noise_floor_dbfs: float
    saturation_ratio: float  # fraction d'échantillons à pleine échelle
    saturated: bool
    simulated: bool
    receiver_id: str
    gain_db: float | None = None

    @property
    def span_hz(self) -> float:
        return float(self.sample_rate_hz)


@dataclass
class Detection:
    """Une émission détectée dans une trame (instantané)."""

    center_freq_hz: float
    bandwidth_hz: float | None  # None : non résolue (≤ résolution spectrale)
    peak_dbfs: float
    channel_power_dbfs: float
    snr_db: float
    low_hz: float
    high_hz: float
    timestamp: float
    excess_db: float = 0.0  # dépassement du plancher (spectre lissé), utilisé pour les seuils


@dataclass
class ActivityEvent:
    """Période d'activité : une émission a dépassé le seuil configuré.

    ATTENTION : un événement signale la présence d'une émission, pas
    l'identification certaine d'un talkie-walkie ou d'un protocole.
    """

    receiver_id: str
    tuned_freq_hz: float  # fréquence centrale configurée du récepteur
    emission_freq_hz: float  # centroïde mesuré de l'émission
    start_ts: float
    end_ts: float
    peak_power_dbfs: float  # puissance de canal maximale sur l'événement (dBFS)
    mean_power_dbfs: float
    snr_db: float
    bandwidth_hz: float | None
    freq_std_hz: float
    detection_params: dict[str, Any]
    simulated: bool
    channel_name: str | None = None
    channel_freq_hz: float | None = None
    frames: int = 0
    classification: str | None = None
    classification_confidence: float | None = None
    id: int | None = None
    kind: str = "émission détectée"

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_ts - self.start_ts)

    @property
    def configured_freq_hz(self) -> float:
        return self.channel_freq_hz if self.channel_freq_hz is not None else self.tuned_freq_hz


@dataclass
class TestResult:
    __test__ = False  # n'est pas une classe de test pytest

    name: str
    passed: bool
    details: dict[str, Any]
    simulated: bool
    receiver_id: str = ""
    timestamp: float = field(default_factory=time.time)
    id: int | None = None
