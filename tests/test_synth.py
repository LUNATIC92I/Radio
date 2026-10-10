import numpy as np
import pytest

from lunatic_radio_lab.dsp.synth import EMITTER_KINDS, Emitter, Scenario, SignalGenerator, preset_scenarios


def test_power_level():
    g = SignalGenerator(Scenario(emitters=[Emitter("carrier", 1e6, -20.0)], noise_dbfs=-100), 250e3)
    x = g.generate(100_000, 1e6)
    assert 10 * np.log10(np.mean(np.abs(x) ** 2)) == pytest.approx(-20.0, abs=0.1)


def test_streaming_is_phase_continuous():
    sc = Scenario(emitters=[Emitter("fm_tone", 1e6 + 5e3, -10.0)], noise_dbfs=-150)
    a = SignalGenerator(sc, 250e3)
    b = SignalGenerator(sc, 250e3)
    whole = a.generate(20_000, 1e6)
    parts = np.concatenate([b.generate(n, 1e6) for n in (3000, 7000, 10_000)])
    assert np.max(np.abs(whole - parts)) < 1e-3


def test_out_of_band_emitter_absent():
    g = SignalGenerator(Scenario(emitters=[Emitter("carrier", 500e6, -10.0)], noise_dbfs=-100), 250e3)
    assert np.mean(np.abs(g.generate(10_000, 446e6)) ** 2) < 1e-8


def test_all_kinds_generate_finite():
    for k in EMITTER_KINDS:
        g = SignalGenerator(Scenario(emitters=[Emitter(k, 1e6, -30.0)]), 250e3)
        assert np.isfinite(g.generate(5000, 1e6)).all()


def test_intermittent_gate():
    g = SignalGenerator(Scenario(emitters=[Emitter("carrier", 1e6, -10.0, on_s=0.1, off_s=0.1)], noise_dbfs=-150), 1e4)
    x = g.generate(2000, 1e6)
    on = np.abs(x) > 0.1
    assert 0.45 < on.mean() < 0.55


def test_scenario_roundtrip_and_presets():
    for sc in preset_scenarios().values():
        assert Scenario.from_dict(sc.to_dict()).to_dict() == sc.to_dict()
    assert {"porteuse", "fm_test", "intermittent", "bruit_eleve", "canaux_occupes", "collision",
            "variations_puissance"} <= set(preset_scenarios())


def test_unknown_kind_rejected():
    g = SignalGenerator(Scenario(emitters=[Emitter("jamming", 1e6, -10)]), 250e3)
    with pytest.raises(ValueError):
        g.generate(100, 1e6)
