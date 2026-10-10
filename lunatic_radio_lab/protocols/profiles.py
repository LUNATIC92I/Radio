"""Profils documentés de familles radio (architecture extensible).

Ces profils décrivent uniquement des propriétés PHYSIQUES publiques (modulation,
débit symbole, canalisation, structure d'accès) issues des normes citées. Ils
servent à la caractérisation et au diagnostic ; ils ne permettent pas de décoder
le contenu des communications. Aucun décodage de voix numérique, aucun traitement
de flux chiffrés n'est implémenté.

Pour ajouter une famille : créer un ``ProtocolProfile`` et l'enregistrer avec
``register_profile``. Le classifieur l'évaluera automatiquement.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BandAllocation:
    low_hz: float
    high_hz: float
    jurisdiction: str
    note: str = ""

    def contains(self, f: float) -> bool:
        return self.low_hz <= f <= self.high_hz


@dataclass(frozen=True)
class ProtocolProfile:
    id: str
    name: str
    family: str
    modulation: str  # cw | fm | 4fsk
    access: str  # FDMA | TDMA | —
    channel_spacing_hz: float | None
    obw_range_hz: tuple[float, float]
    deviation_peak_range_hz: tuple[float, float] | None = None
    symbol_rate_hz: float | None = None
    fsk_levels: int | None = None
    burst_period_ms: float | None = None
    burst_length_ms: float | None = None
    test_tone_hz: float | None = None
    bands: tuple[BandAllocation, ...] = ()
    references: tuple[str, ...] = ()
    confidence_cap: float = 0.9
    diagnostic_scope: str = "Mesures physiques uniquement (aucun décodage de contenu)."
    notes: tuple[str, ...] = ()
    ambiguous_with: tuple[str, ...] = field(default_factory=tuple)


_PMR446_EU = BandAllocation(
    446.0e6, 446.2e6, "UE/CEPT",
    "PMR446 sans licence (décision ECC/DEC/(15)05) ; vérifier la transposition nationale. "
    "Non autorisé aux États-Unis (service FRS/GMRS distinct).",
)

PROFILES: dict[str, ProtocolProfile] = {}


def register_profile(p: ProtocolProfile) -> None:
    if p.id in PROFILES:
        raise ValueError(f"Profil déjà enregistré : {p.id}")
    PROFILES[p.id] = p


def get_profile(pid: str) -> ProtocolProfile:
    return PROFILES[pid]


def all_profiles() -> list[ProtocolProfile]:
    return list(PROFILES.values())


for _p in (
    ProtocolProfile(
        id="test_cw", name="Porteuse de test non modulée (CW)", family="Équipement de test",
        modulation="cw", access="—", channel_spacing_hz=None, obw_range_hz=(0.0, 1_000.0),
        references=("Mesure de laboratoire",), confidence_cap=0.9,
        notes=("Une porteuse pure peut aussi être une raie parasite (oscillateur local, harmonique).",),
    ),
    ProtocolProfile(
        id="test_fm_1k", name="Signal de test FM, tonalité 1 kHz", family="Équipement de test",
        modulation="fm", access="—", channel_spacing_hz=None, obw_range_hz=(1_000.0, 16_000.0),
        deviation_peak_range_hz=(300.0, 5_500.0), test_tone_hz=1_000.0,
        references=("TIA-603-E (mesures SINAD)", "ETSI EN 300 086"), confidence_cap=0.85,
        notes=("Tonalité 1 kHz : signal d'essai usuel des générateurs RF et des bancs de test.",),
    ),
    ProtocolProfile(
        id="fm_nb", name="FM analogique bande étroite (12,5 kHz)", family="Radios analogiques FM",
        modulation="fm", access="FDMA", channel_spacing_hz=12_500.0, obw_range_hz=(1_500.0, 11_500.0),
        deviation_peak_range_hz=(300.0, 2_900.0),
        references=("ETSI EN 300 086", "ETSI EN 300 296", "TIA-603-E"), confidence_cap=0.8,
        ambiguous_with=("pmr446_analog", "fm_wb"),
    ),
    ProtocolProfile(
        id="fm_wb", name="FM analogique 25 kHz", family="Radios analogiques FM",
        modulation="fm", access="FDMA", channel_spacing_hz=25_000.0, obw_range_hz=(8_000.0, 20_000.0),
        deviation_peak_range_hz=(2_500.0, 5_500.0),
        references=("ETSI EN 300 086",), confidence_cap=0.75,
    ),
    ProtocolProfile(
        id="pmr446_analog", name="PMR446 analogique (FM 12,5 kHz)", family="PMR446",
        modulation="fm", access="FDMA", channel_spacing_hz=12_500.0, obw_range_hz=(1_500.0, 11_500.0),
        deviation_peak_range_hz=(300.0, 2_900.0), bands=(_PMR446_EU,),
        references=("ECC/DEC/(15)05", "ETSI EN 303 405"), confidence_cap=0.75,
        notes=("La bande seule ne prouve pas qu'il s'agit d'un équipement PMR446.",),
        ambiguous_with=("fm_nb",),
    ),
    ProtocolProfile(
        id="dmr", name="DMR (ETSI TS 102 361) — TDMA 2 créneaux", family="DMR",
        modulation="4fsk", access="TDMA", channel_spacing_hz=12_500.0, obw_range_hz=(3_000.0, 11_000.0),
        deviation_peak_range_hz=(1_400.0, 3_000.0), symbol_rate_hz=4_800.0, fsk_levels=4,
        burst_period_ms=60.0, burst_length_ms=27.5, bands=(_PMR446_EU,),
        references=("ETSI TS 102 361-1 (couche physique 4FSK, ±648/±1944 Hz)",),
        confidence_cap=0.6,
        notes=(
            "Plafond de confiance 60 % : les motifs de synchronisation ETSI ne sont pas vérifiés.",
            "Un relais DMR émet en continu : il ressemble alors à un signal 4FSK FDMA.",
        ),
        ambiguous_with=("p25_p1",),
    ),
    ProtocolProfile(
        id="fsk4_4800", name="Numérique 4FSK 4800 Bd, 12,5 kHz (DMR ou P25 Phase 1 — non déterminé)",
        family="Numérique 12,5 kHz",
        modulation="4fsk", access="—", channel_spacing_hz=12_500.0, obw_range_hz=(3_000.0, 11_000.0),
        deviation_peak_range_hz=(1_400.0, 3_000.0), symbol_rate_hz=4_800.0, fsk_levels=4,
        references=("ETSI TS 102 361-1", "TIA-102.BAAA-B"), confidence_cap=0.55,
        notes=("Hypothèse de famille : la couche physique est commune ; l'accès (TDMA/FDMA) ou la "
               "vérification des trames permettrait de trancher.",),
    ),
    ProtocolProfile(
        id="p25_p1", name="P25 Phase 1 (C4FM, FDMA)", family="P25",
        modulation="4fsk", access="FDMA", channel_spacing_hz=12_500.0, obw_range_hz=(3_000.0, 11_000.0),
        deviation_peak_range_hz=(1_400.0, 3_000.0), symbol_rate_hz=4_800.0, fsk_levels=4,
        references=("TIA-102.BAAA-B (C4FM, ±600/±1800 Hz)",),
        confidence_cap=0.5,
        notes=(
            "Plafond de confiance 50 % : sans vérification des trames, un signal 4FSK 4800 Bd continu "
            "peut aussi être un relais DMR ou un autre système.",
            "P25 Phase 2 (TDMA H-DQPSK/H-CPM) n'est pas caractérisé par cette version.",
        ),
        ambiguous_with=("dmr",),
    ),
    ProtocolProfile(
        id="fsk4_6k25", name="4FSK 2400 Bd, 6,25 kHz (famille dPMR / NXDN 6,25)", family="Numérique 6,25 kHz",
        modulation="4fsk", access="FDMA", channel_spacing_hz=6_250.0, obw_range_hz=(1_500.0, 6_000.0),
        deviation_peak_range_hz=(600.0, 1_600.0), symbol_rate_hz=2_400.0, fsk_levels=4,
        bands=(_PMR446_EU,),
        references=("ETSI TS 102 490 (dPMR446)", "ETSI TS 102 658 (dPMR)"), confidence_cap=0.5,
        notes=("dPMR et NXDN 6,25 kHz partagent la même couche physique : non distinguables ici.",),
    ),
):
    register_profile(_p)


def pmr446_channel_plan() -> list[tuple[str, float, float]]:
    """Plan public des 16 canaux analogiques PMR446 (UE) : (nom, fréquence, largeur)."""
    return [(f"PMR446 CH{i + 1:02d}", 446.00625e6 + 12_500.0 * i, 12_500.0) for i in range(16)]


def bands_containing(freq_hz: float) -> list[tuple[ProtocolProfile, BandAllocation]]:
    out = []
    for p in PROFILES.values():
        for b in p.bands:
            if b.contains(freq_hz):
                out.append((p, b))
    return out
