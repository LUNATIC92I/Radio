import pytest

from conftest import gen
from lunatic_radio_lab.dsp.classifier import DECISION_THRESHOLD, classify_iq
from lunatic_radio_lab.dsp.features import extract_features
from lunatic_radio_lab.dsp.synth import Emitter
from lunatic_radio_lab.protocols.profiles import PROFILES

FC, OFF = 446.1e6, 10e3


def cls(em, noise=-60.0, seconds=1.0):
    return classify_iq(gen([em], seconds, noise=noise), 250e3, OFF, FC, simulated=True)


@pytest.mark.parametrize("em,expected", [
    (Emitter("carrier", FC + OFF, -40), "test_cw"),
    (Emitter("fm_tone", FC + OFF, -40), "test_fm_1k"),
    (Emitter("fm_voice", FC + OFF, -40, ctcss_hz=123.0), "fm_nb"),
    (Emitter("fsk4_tdma", FC + OFF, -40, deviation_hz=1944, embed_sync=True), "dmr"),
    (Emitter("fsk4_tdma", FC + OFF, -40, deviation_hz=1944), "fsk4_4800"),
    (Emitter("fsk4_cont", FC + OFF, -40, deviation_hz=1800), "fsk4_4800"),
    (Emitter("fsk4_cont", FC + OFF, -40, deviation_hz=1800, embed_sync=True), "p25_p1"),
    (Emitter("fsk4_narrow", FC + OFF, -40, deviation_hz=1050, symbol_rate=2400), "fsk4_6k25"),
])
def test_expected_hypothesis(em, expected):
    c = cls(em)
    assert c.best.profile_id == expected
    assert c.best.confidence >= DECISION_THRESHOLD
    assert c.best.supporting  # toujours justifié
    prof = PROFILES[expected]
    assert c.best.confidence <= max(prof.confidence_cap, prof.confidence_cap_verified or 0) + 1e-9


def test_digital_never_certain():
    c = cls(Emitter("fsk4_tdma", FC + OFF, -30, deviation_hz=1944))
    assert all(h.confidence <= 0.6 + 1e-9 for h in c.hypotheses if h.profile_id in ("dmr", "p25_p1", "fsk4_4800"))
    assert "non déterminé" in c.verdict
    # même avec le motif de synchronisation, la confiance reste < 100 %
    c2 = cls(Emitter("fsk4_tdma", FC + OFF, -30, deviation_hz=1944, embed_sync=True))
    assert c2.best.confidence <= 0.9 + 1e-9
    assert any("synchronisation" in s for s in c2.best.supporting)
    assert any("Motifs de synchronisation" in o for o in c2.observations)


@pytest.mark.parametrize("em", [Emitter("fm_voice", FC + OFF, -78), Emitter("noise_burst", FC + OFF, -40)])
def test_insufficient_evidence_not_identified(em):
    c = cls(em)
    assert c.verdict.startswith("Non identifié")


def test_observations_and_simulated_flag():
    c = cls(Emitter("fm_tone", FC + OFF, -40, ctcss_hz=88.5))
    assert c.observations[0].startswith("DONNÉES SIMULÉES")
    assert c.features.ctcss_hz == 88.5
    assert any("CTCSS" in o for o in c.observations)
    d = c.to_dict()
    assert d["simulated"] and d["hypotheses"]


def test_features_tdma_structure():
    f = extract_features(gen([Emitter("fsk4_tdma", FC + OFF, -40, deviation_hz=1944)], 1.0), 250e3, OFF)
    assert f.burst_period_ms == pytest.approx(60.0, abs=2)
    assert f.burst_mean_ms == pytest.approx(27.5, abs=3)
    assert f.symbol_rate_hz == pytest.approx(4800, rel=0.01)
    assert f.fsk_levels == 4


def test_frequency_drift_measured():
    f = extract_features(gen([Emitter("carrier", FC + OFF, -40, drift_hz_per_s=200.0)], 1.0), 250e3, OFF)
    assert f.freq_drift_hz_s == pytest.approx(200.0, rel=0.1)


def test_too_short_capture():
    f = extract_features(gen([Emitter("carrier", FC + OFF, -40)], 0.01), 250e3, OFF)
    assert f.warnings and f.snr_db is None


def test_collision_flagged():
    from lunatic_radio_lab.dsp.synth import Scenario, SignalGenerator
    sc = Scenario(emitters=[Emitter("fm_voice", FC + OFF, -40.0, on_s=3.0, off_s=3.0),
                            Emitter("fm_tone", FC + OFF + 300, -43.0, tone_hz=1750, on_s=1.0, off_s=5.0, phase_s=1.5)])
    x = SignalGenerator(sc, 250e3).generate(int(3.0 * 250e3), FC)
    f = extract_features(x[int(0.5 * 250e3):], 250e3, OFF)
    assert f.overlap_suspected
    clean = extract_features(gen([Emitter("fm_voice", FC + OFF, -40)], 2.0), 250e3, OFF)
    assert not clean.overlap_suspected
    tdma = extract_features(gen([Emitter("fsk4_tdma", FC + OFF, -40, deviation_hz=1944)], 1.0), 250e3, OFF)
    assert not tdma.overlap_suspected  # les fronts de rafales ne sont pas des collisions
