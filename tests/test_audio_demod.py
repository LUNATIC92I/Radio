import numpy as np
import pytest

from conftest import gen
from lunatic_radio_lab.dsp import audio as A
from lunatic_radio_lab.dsp.demod import channelize, fm_demodulate, instantaneous_frequency
from lunatic_radio_lab.dsp.synth import Emitter


def tone_clip(f=1000.0, amp=0.5, sr=16000, dur=2.0):
    t = np.arange(int(sr * dur)) / sr
    return A.AudioClip((amp * np.sin(2 * np.pi * f * t)).astype(np.float32), sr)


def test_levels():
    lv = A.measure_levels(tone_clip(amp=0.5))
    assert lv.peak_dbfs == pytest.approx(-6.02, abs=0.05)
    assert lv.rms_dbfs == pytest.approx(-9.03, abs=0.05)
    assert lv.crest_factor_db == pytest.approx(3.01, abs=0.05)


def test_normalize_peak():
    c = A.normalize(tone_clip(amp=0.1), -1.0)
    assert A.measure_levels(c).peak_dbfs == pytest.approx(-1.0, abs=0.05)


def test_bandpass_removes_ctcss():
    sr = 16000
    t = np.arange(sr * 2) / sr
    x = 0.3 * np.sin(2 * np.pi * 88.5 * t) + 0.3 * np.sin(2 * np.pi * 1000 * t)
    y = A.bandpass(A.AudioClip(x.astype(np.float32), sr), 300, 3400).samples
    spec = np.abs(np.fft.rfft(y[4000:-4000]))
    f = np.fft.rfftfreq(len(y) - 8000, 1 / sr)
    assert spec[np.argmin(np.abs(f - 88.5))] < 0.01 * spec[np.argmin(np.abs(f - 1000))]


def test_noise_reduction_improves_snr():
    clip = A.synthetic_test_clip(noise_dbfs=-30)
    out = A.reduce_noise(clip, 15)
    gate = ((np.arange(len(clip.samples)) / clip.sample_rate) % 1.0) >= 0.7  # zones sans tonalité
    assert np.std(out.samples[gate]) < 0.5 * np.std(clip.samples[gate])


def test_trim_autotrim_and_wav_roundtrip(tmp_path):
    c = tone_clip()
    assert A.trim(c, 0.5, 1.0).duration_s == pytest.approx(0.5, abs=1e-3)
    with pytest.raises(ValueError):
        A.trim(c, 1.0, 0.5)
    sr = 16000
    x = np.zeros(sr * 3, np.float32)
    x[sr:2 * sr] = 0.5 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr)
    assert A.auto_trim_silence(A.AudioClip(x, sr)).duration_s == pytest.approx(1.2, abs=0.1)
    p = A.save_wav(c, tmp_path / "a.wav")
    back = A.load_audio(p)
    assert back.sample_rate == 16000 and np.max(np.abs(back.samples - c.samples)) < 1e-3


@pytest.mark.skipif(not A.ffmpeg_available(), reason="FFmpeg absent")
def test_ffmpeg_conversion(tmp_path):
    import subprocess
    p = A.save_wav(tone_clip(), tmp_path / "a.wav")
    flac = tmp_path / "a.flac"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(p), str(flac)], check=True)
    assert A.load_audio(flac).duration_s == pytest.approx(2.0, abs=0.05)


def test_unsupported_format(tmp_path):
    (tmp_path / "x.xyz").write_bytes(b"0")
    with pytest.raises(ValueError):
        A.load_audio(tmp_path / "x.xyz")


def test_fm_demod_recovers_test_tone():
    fs = 250e3
    iq = gen([Emitter("fm_tone", 446.1e6 + 20e3, -30, deviation_hz=2500, tone_hz=1000)], 1.0)
    x, fs2 = channelize(iq, fs, 20e3, 12_500, min_rate=32_000)
    audio = fm_demodulate(x, fs2, 16_000, 2_500)
    spec = np.abs(np.fft.rfft(audio[2000:]))
    f = np.fft.rfftfreq(len(audio) - 2000, 1 / 16000)
    assert f[np.argmax(spec)] == pytest.approx(1000, abs=5)


def test_instantaneous_frequency_of_offset_carrier():
    fs = 100e3
    n = np.arange(10000)
    x = np.exp(2j * np.pi * 1234.0 * n / fs)
    assert np.mean(instantaneous_frequency(x, fs)) == pytest.approx(1234.0, abs=0.5)
