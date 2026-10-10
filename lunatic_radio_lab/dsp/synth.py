"""Générateur de signaux IQ synthétiques (mode laboratoire, AUCUNE émission radio).

Toutes les données produites ici sont SIMULÉES et marquées comme telles par les
couches supérieures. Les signaux numériques générés (4FSK) ne contiennent aucune
trame de protocole réel : ce sont des suites de symboles aléatoires dont seules les
propriétés physiques (débit, excursion, structure TDMA) imitent les familles
documentées, afin de tester la chaîne de caractérisation.

Le générateur est « en flux » : les appels successifs à ``generate`` produisent un
signal continu (phases et états des filtres conservés), y compris après un
changement de fréquence centrale.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from scipy import signal as sps

EMITTER_KINDS = {
    "carrier": "Porteuse stable (CW)",
    "fm_tone": "FM de test (tonalité 1 kHz)",
    "fm_voice": "FM analogique, modulation vocale synthétique",
    "fsk4_tdma": "4FSK 4800 Bd, rafales TDMA 30/60 ms (type DMR, synthétique)",
    "fsk4_cont": "4FSK 4800 Bd continu (type C4FM, synthétique)",
    "fsk4_narrow": "4FSK 2400 Bd continu (type 6,25 kHz, synthétique)",
    "noise_burst": "Bruit large bande impulsionnel",
}


@dataclass
class Emitter:
    kind: str = "fm_voice"
    freq_hz: float = 446.00625e6
    power_dbfs: float = -30.0
    deviation_hz: float = 2_500.0
    tone_hz: float = 1_000.0
    ctcss_hz: float | None = None
    symbol_rate: float = 4_800.0
    bandwidth_hz: float = 10_000.0  # pour noise_burst
    on_s: float | None = None  # None => émission permanente
    off_s: float = 0.0
    phase_s: float = 0.0
    fading_depth_db: float = 0.0
    fading_rate_hz: float = 0.2
    drift_hz_per_s: float = 0.0
    label: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Emitter:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def describe(self) -> str:
        return self.label or EMITTER_KINDS.get(self.kind, self.kind)


@dataclass
class Scenario:
    name: str = "Scénario"
    description: str = ""
    noise_dbfs: float = -60.0  # puissance totale de bruit sur la bande d'échantillonnage
    emitters: list[Emitter] = field(default_factory=list)
    seed: int = 1234

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["emitters"] = [e.to_dict() for e in self.emitters]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scenario:
        return cls(
            name=d.get("name", "Scénario"),
            description=d.get("description", ""),
            noise_dbfs=float(d.get("noise_dbfs", -60.0)),
            emitters=[Emitter.from_dict(e) for e in d.get("emitters", [])],
            seed=int(d.get("seed", 1234)),
        )


def _shaping_filter(sps_ratio: float, bt: float = 0.5) -> np.ndarray:
    """Filtre gaussien de mise en forme des impulsions de fréquence (normalisé)."""
    span = 4
    n = max(3, int(round(span * sps_ratio)) | 1)
    t = (np.arange(n) - (n - 1) / 2) / sps_ratio
    sigma = math.sqrt(math.log(2)) / (2 * math.pi * bt)
    h = np.exp(-0.5 * (t / sigma) ** 2)
    return h / h.sum()


class _EmitterState:
    def __init__(self, em: Emitter, sample_rate: float, rng: np.random.Generator):
        self.em = em
        self.phase = 0.0  # phase porteuse (rad)
        self.mod_phase = 0.0  # phase tonalité / voix
        self.ctcss_phase = 0.0
        self.f0_phase = 0.0
        self.rng = rng
        self.symbols = rng.integers(0, 4, size=1 << 15)
        self.zi: np.ndarray | None = None
        self.fs = sample_rate
        self.h = _shaping_filter(sample_rate / em.symbol_rate) if em.kind.startswith("fsk4") else None
        self.noise_zi: np.ndarray | None = None
        bw = min(em.bandwidth_hz, 0.9 * sample_rate)
        self.noise_b = sps.firwin(63, bw / 2, fs=sample_rate) if em.kind == "noise_burst" else None


# Niveaux 4FSK normalisés (±1/3, ±1) × excursion max
_FSK_LEVELS = np.array([-3.0, -1.0, 1.0, 3.0]) / 3.0


class SignalGenerator:
    """Génère des blocs IQ complexes (complex64) selon un scénario."""

    def __init__(self, scenario: Scenario, sample_rate: float):
        self.scenario = scenario
        self.sample_rate = float(sample_rate)
        self.t = 0.0  # temps absolu du prochain échantillon (s)
        self.rng = np.random.default_rng(scenario.seed)
        self._states = [
            _EmitterState(e, self.sample_rate, np.random.default_rng(scenario.seed + 17 * (i + 1)))
            for i, e in enumerate(scenario.emitters)
        ]

    def set_sample_rate(self, sample_rate: float) -> None:
        if sample_rate != self.sample_rate:
            t = self.t
            self.__init__(self.scenario, sample_rate)  # type: ignore[misc]
            self.t = t

    def _gate(self, em: Emitter, t: np.ndarray) -> np.ndarray:
        if em.on_s is None:
            return np.ones_like(t, dtype=bool)
        period = em.on_s + em.off_s
        return ((t - em.phase_s) % period) < em.on_s

    def _amplitude(self, em: Emitter, t: np.ndarray) -> np.ndarray:
        p_db = em.power_dbfs
        if em.fading_depth_db:
            p_db = p_db + 0.5 * em.fading_depth_db * np.sin(2 * np.pi * em.fading_rate_hz * t)
        return np.sqrt(10.0 ** (np.asarray(p_db) / 10.0))

    def _voice(self, st: _EmitterState, t: np.ndarray) -> np.ndarray:
        """Signal pseudo-vocal : fondamental variable + harmoniques + enveloppe syllabique."""
        fs = self.sample_rate
        f0 = 150.0 + 40.0 * np.sin(2 * np.pi * 0.7 * t)
        ph = st.f0_phase + 2 * np.pi * np.cumsum(f0) / fs
        st.f0_phase = float(ph[-1] % (2 * np.pi))
        sig = np.zeros_like(t)
        for k, a in ((1, 1.0), (2, 0.6), (3, 0.5), (5, 0.35), (8, 0.25), (12, 0.15), (16, 0.08)):
            sig += a * np.sin(k * ph)
        env = (0.5 * (1 + np.sin(2 * np.pi * 3.3 * t))) ** 2
        env *= 0.6 + 0.4 * (0.5 * (1 + np.sin(2 * np.pi * 0.37 * t)))
        sig = sig * env
        return sig / 2.2  # amplitude crête ≈ 1

    def _render(self, st: _EmitterState, n: int, t: np.ndarray, center_freq: float) -> np.ndarray | None:
        em = st.em
        fs = self.sample_rate
        offset = em.freq_hz - center_freq + em.drift_hz_per_s * t
        half = fs / 2
        if np.all(np.abs(offset) > half + 50_000):
            # hors bande : on fait quand même avancer les états de modulation
            st.phase = 0.0
            return None
        gate = self._gate(em, t)
        amp = self._amplitude(em, t) * gate

        if em.kind == "noise_burst":
            w = (st.rng.standard_normal(n) + 1j * st.rng.standard_normal(n)) / math.sqrt(2)
            if st.noise_zi is None:
                st.noise_zi = np.zeros(len(st.noise_b) - 1, dtype=complex)
            w, st.noise_zi = sps.lfilter(st.noise_b, 1.0, w, zi=st.noise_zi)
            w = w / math.sqrt(np.sum(st.noise_b**2))
            ph = st.phase + 2 * np.pi * np.cumsum(offset) / fs
            st.phase = float(ph[-1] % (2 * np.pi))
            return amp * w * np.exp(1j * ph)

        if em.kind == "carrier":
            inst = np.zeros(n)
        elif em.kind == "fm_tone":
            inst = em.deviation_hz * np.sin(2 * np.pi * em.tone_hz * t)
        elif em.kind == "fm_voice":
            inst = em.deviation_hz * 0.85 * self._voice(st, t)
        elif em.kind.startswith("fsk4"):
            sym_idx = np.floor(t * em.symbol_rate).astype(np.int64) % len(st.symbols)
            levels = _FSK_LEVELS[st.symbols[sym_idx]] * em.deviation_hz
            if st.zi is None:
                st.zi = sps.lfilter_zi(st.h, 1.0) * levels[0]
            inst, st.zi = sps.lfilter(st.h, 1.0, levels, zi=st.zi)
            if em.kind == "fsk4_tdma":
                # rafales de 27,5 ms toutes les 60 ms (créneau de 30 ms)
                gate = gate & (((t - em.phase_s) % 0.060) < 0.0275)
                amp = self._amplitude(em, t) * gate
        else:
            raise ValueError(f"Type d'émetteur inconnu : {em.kind}")

        if em.ctcss_hz and em.kind in ("fm_voice", "fm_tone", "carrier"):
            inst = inst + 0.15 * em.deviation_hz * np.sin(2 * np.pi * em.ctcss_hz * t)

        ph = st.phase + 2 * np.pi * np.cumsum(offset + inst) / fs
        st.phase = float(ph[-1] % (2 * np.pi))
        return amp * np.exp(1j * ph)

    def generate(self, n: int, center_freq: float) -> np.ndarray:
        fs = self.sample_rate
        t = self.t + np.arange(n) / fs
        out = np.zeros(n, dtype=np.complex128)
        for st in self._states:
            if not st.em.enabled:
                continue
            sig = self._render(st, n, t, center_freq)
            if sig is not None:
                out += sig
        sigma = math.sqrt(10.0 ** (self.scenario.noise_dbfs / 10.0) / 2.0)
        out += sigma * (self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n))
        self.t += n / fs
        return out.astype(np.complex64)


# --------------------------------------------------------------------------- scénarios
PMR446_ANALOG_CH = [446.00625e6 + 12_500 * i for i in range(16)]


def preset_scenarios() -> dict[str, Scenario]:
    """Scénarios prédéfinis du mode laboratoire (centrés sur 446,1 MHz)."""
    ch = PMR446_ANALOG_CH
    return {
        "porteuse": Scenario(
            "Porteuse stable",
            "Une porteuse non modulée à -30 dBFS ; sert à vérifier l'étalonnage fréquence/puissance.",
            -65.0,
            [Emitter("carrier", 446.1e6 + 20_000, -30.0, label="Porteuse de référence")],
        ),
        "fm_test": Scenario(
            "FM de test",
            "Tonalité 1 kHz, excursion 2,5 kHz, CTCSS 88,5 Hz, sur le canal PMR446 n°3.",
            -60.0,
            [Emitter("fm_tone", ch[2], -35.0, 2_500.0, 1_000.0, ctcss_hz=88.5, label="FM test 1 kHz")],
        ),
        "intermittent": Scenario(
            "Émissions intermittentes",
            "Alternats de type talkie-walkie sur trois canaux, avec évanouissements.",
            -60.0,
            [
                Emitter("fm_voice", ch[0], -38.0, on_s=2.0, off_s=3.0, phase_s=0.5, label="Station A (simulée)"),
                Emitter("fm_voice", ch[5], -45.0, on_s=1.5, off_s=4.5, phase_s=2.0, fading_depth_db=8.0,
                        label="Station B (simulée)"),
                Emitter("fm_voice", ch[11], -50.0, ctcss_hz=123.0, on_s=3.0, off_s=2.0, phase_s=1.0,
                        label="Station C (simulée)"),
            ],
        ),
        "bruit_eleve": Scenario(
            "Bruit élevé",
            "Émission faible (SNR réduit) dans un bruit élevé : évalue les seuils de détection.",
            -42.0,
            [Emitter("fm_voice", ch[7], -48.0, on_s=2.0, off_s=2.0, label="Station faible (simulée)")],
        ),
        "canaux_occupes": Scenario(
            "Canaux occupés",
            "Plusieurs canaux occupés en permanence, plus des signaux numériques synthétiques.",
            -62.0,
            [
                Emitter("fm_voice", ch[1], -40.0, label="FM permanente"),
                Emitter("fsk4_tdma", ch[8], -42.0, deviation_hz=1_944.0, label="4FSK TDMA synthétique"),
                Emitter("fsk4_cont", ch[13], -44.0, deviation_hz=1_800.0, label="4FSK continu synthétique"),
                Emitter("carrier", ch[15], -50.0, label="Porteuse"),
            ],
        ),
        "collision": Scenario(
            "Collision de transmissions",
            "Deux stations simulées émettent simultanément sur le même canal (chevauchement).",
            -60.0,
            [
                Emitter("fm_voice", ch[4], -40.0, on_s=3.0, off_s=3.0, phase_s=0.0, label="Station 1 (simulée)"),
                Emitter("fm_tone", ch[4] + 300.0, -43.0, tone_hz=1_750.0, on_s=2.0, off_s=4.0, phase_s=1.5,
                        label="Station 2 (simulée, chevauchement)"),
            ],
        ),
        "variations_puissance": Scenario(
            "Variations de puissance",
            "Émission permanente avec évanouissement lent de 20 dB et dérive de fréquence.",
            -60.0,
            [
                Emitter("fm_tone", ch[6], -35.0, fading_depth_db=20.0, fading_rate_hz=0.1,
                        drift_hz_per_s=15.0, label="Émetteur à évanouissement"),
            ],
        ),
    }
