import numpy as np
import pytest

from lunatic_radio_lab.dsp.spectrum import (
    SpectrumAnalyzer, band_power_db, dynamic_range_db, saturation_ratio, welch_psd, window_info,
)


def tone(f, fs=250e3, n=65536, amp=1.0):
    t = np.arange(n) / fs
    return (amp * np.exp(2j * np.pi * f * t)).astype(np.complex64)


def test_full_scale_tone_is_0_dbfs_on_bin_center():
    fs, n = 250e3, 4096
    f = 32 * fs / n
    fr = SpectrumAnalyzer(n).process(tone(f), 0.0, fs)
    k = int(np.argmax(fr.power_dbfs))
    assert fr.freqs_hz[k] == pytest.approx(f)
    assert fr.power_dbfs[k] == pytest.approx(0.0, abs=0.05)


@pytest.mark.parametrize("amp_db", [-20.0, -45.0])
def test_band_power_matches_tone_power(amp_db):
    fs, n = 250e3, 4096
    x = tone(12_345.0, amp=10 ** (amp_db / 20))
    fr = SpectrumAnalyzer(n).process(x, 0.0, fs)
    sel = np.abs(fr.freqs_hz - 12_345.0) < 2_000
    assert band_power_db(fr.power_dbfs.astype(float), fr.enbw_bins, sel) == pytest.approx(amp_db, abs=0.2)


def test_noise_floor_and_rbw(rng):
    fs, n = 250e3, 2048
    sigma2 = 1e-6
    x = (np.sqrt(sigma2 / 2) * (rng.standard_normal(200_000) + 1j * rng.standard_normal(200_000))).astype(np.complex64)
    fr = SpectrumAnalyzer(n, window="hann").process(x, 0.0, fs)
    wi = window_info("hann", n)
    expected = 10 * np.log10(sigma2 * wi.enbw_bins / n)
    assert fr.noise_floor_dbfs == pytest.approx(expected, abs=1.0)
    assert fr.rbw_hz == pytest.approx(1.5 * fs / n, rel=0.01)  # ENBW Hann = 1,5 case


def test_saturation_detection():
    x = tone(1000.0, amp=1.5)
    x = np.clip(x.real, -1, 1) + 1j * np.clip(x.imag, -1, 1)
    assert saturation_ratio(x) > 0.1
    assert saturation_ratio(tone(1000.0, amp=0.5)) == 0.0
    fr = SpectrumAnalyzer(1024).process(x.astype(np.complex64), 0, 250e3)
    assert fr.saturated


def test_invalid_parameters():
    with pytest.raises(ValueError):
        welch_psd(np.zeros(100, complex), fft_size=1000)
    with pytest.raises(ValueError):
        welch_psd(np.zeros(4096, complex), overlap=1.0)


def test_dynamic_range():
    assert dynamic_range_db(8) == pytest.approx(49.9, abs=0.1)
    assert dynamic_range_db(None) is None


def test_frequency_axis_centered():
    fr = SpectrumAnalyzer(1024).process(tone(0.0, n=4096), 446.1e6, 250e3)
    assert fr.freqs_hz[512] == pytest.approx(446.1e6)
    assert fr.freqs_hz[0] == pytest.approx(446.1e6 - 125e3)
