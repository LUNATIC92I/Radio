import pytest

from conftest import gen
from lunatic_radio_lab.dsp.detection import DetectionParams, channel_power, detect_emissions, occupied_bandwidth
from lunatic_radio_lab.dsp.spectrum import SpectrumAnalyzer
from lunatic_radio_lab.dsp.synth import Emitter

FC, FS = 446.1e6, 250e3


def frame(emitters, noise=-60.0, n=4096):
    return SpectrumAnalyzer(n).process(gen(emitters, 0.5, noise=noise), FC, FS)


def test_detects_carrier_with_correct_frequency_and_power():
    fr = frame([Emitter("carrier", FC + 40_000, -40.0)])
    d = detect_emissions(fr)
    assert len(d) == 1
    assert d[0].center_freq_hz == pytest.approx(FC + 40_000, abs=FS / 4096)
    assert d[0].channel_power_dbfs == pytest.approx(-40.0, abs=0.5)
    assert d[0].bandwidth_hz is None or d[0].bandwidth_hz < 1_000  # non résolue / étroite


def test_fm_bandwidth_measured():
    fr = frame([Emitter("fm_tone", FC - 30_000, -40.0, deviation_hz=2_500, tone_hz=1_000)])
    d = detect_emissions(fr)
    assert len(d) == 1
    # Carson : 2·(2,5 + 1) = 7 kHz ; l'OBW 99 % doit être du même ordre
    assert 4_000 < d[0].bandwidth_hz < 10_000


def test_noise_only_gives_no_detection():
    assert detect_emissions(frame([])) == []


def test_multiple_emitters_and_dc_exclusion():
    em = [Emitter("carrier", FC, -40.0), Emitter("carrier", FC + 50_000, -45.0)]
    fr = frame(em)
    assert len(detect_emissions(fr)) == 2
    assert len(detect_emissions(fr, DetectionParams(dc_exclude_hz=2_000))) == 1


def test_bandwidth_filters():
    fr = frame([Emitter("fm_tone", FC + 20_000, -40.0), Emitter("carrier", FC - 40_000, -40.0)])
    wide = detect_emissions(fr, DetectionParams(min_bandwidth_hz=3_000))
    assert len(wide) == 1 and wide[0].center_freq_hz > FC


def test_channel_power_and_occupied_bandwidth():
    fr = frame([Emitter("carrier", FC + 10_000, -30.0)])
    p, snr = channel_power(fr, FC + 10_000, 12_500)
    assert p == pytest.approx(-30.0, abs=0.5)
    assert snr > 20
    import numpy as np
    bw, lo, hi = occupied_bandwidth(np.ones(100), 10.0, 0.99)
    assert bw == pytest.approx(1000.0, abs=20)
