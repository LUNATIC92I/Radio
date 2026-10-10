import wave

import numpy as np
import pytest

from conftest import gen
from lunatic_radio_lab.channels import AuthorizedChannel, ChannelManager
from lunatic_radio_lab.dsp.demod import StreamingFMDemodulator
from lunatic_radio_lab.dsp.spectrum import SpectrumAnalyzer
from lunatic_radio_lab.dsp.synth import Emitter, Scenario
from lunatic_radio_lab.drivers.simulated import SimulatedReceiver
from lunatic_radio_lab.engine import AcquisitionEngine
from lunatic_radio_lab.models import ReceiverConfig

FC, FS = 446.1e6, 250e3


def run_stream(iq, offset, block=8192, squelch=8.0):
    d = StreamingFMDemodulator(FS, offset, squelch_db=squelch)
    sa = SpectrumAnalyzer(4096)
    out, sq = [], []
    for i in range(0, len(iq), block):
        b = iq[i:i + block]
        fr = sa.process(b, 0.0, FS)
        d.set_noise_floor(fr.noise_floor_dbfs, fr.rbw_hz)
        out.append(d.process(b))
        sq.append(d.squelch_open)
    return np.concatenate(out), sq


@pytest.mark.parametrize("block", [8192, 5000, 777])
def test_streaming_demod_is_continuous(block):
    iq = gen([Emitter("fm_tone", FC + 20e3, -35, deviation_hz=2500, tone_hz=1000)], 1.5)
    audio, _ = run_stream(iq, 20e3, block)
    assert len(audio) == pytest.approx(1.5 * 16000, abs=40)
    seg = audio[4000:20000]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    f = np.fft.rfftfreq(len(seg), 1 / 16000)
    assert f[np.argmax(spec)] == pytest.approx(1000, abs=2)
    assert spec[np.abs(f - 1000) < 30].sum() / spec.sum() > 0.995  # pas de clics aux jointures


def test_squelch_follows_transmissions():
    iq = gen([Emitter("fm_tone", FC + 20e3, -40, on_s=1.0, off_s=1.0)], 4.0)
    audio, sq = run_stream(iq, 20e3)
    sq = np.array(sq)
    n = len(sq)
    assert sq[: n // 4 - 2].all() and not sq[n // 4 + 2: n // 2 - 2].any()
    noise_only, sq2 = run_stream(gen([], 1.0), 20e3)
    assert not any(sq2) and np.all(noise_only == 0)


def test_monitor_authorization_rules(db, unlocked):
    m = ChannelManager(db, unlocked)
    assert m.monitor_authorization(446e6, 12_500, simulated=True, record=True)[0]
    ok, _, why = m.monitor_authorization(446.00625e6, 12_500, simulated=False, record=False)
    assert not ok and "aucun canal" in why
    m.save(AuthorizedChannel("Lab", 446.00625e6, 12_500, authorization_ref=""))
    ok, _, why = m.monitor_authorization(446.00625e6, 12_500, simulated=False, record=False)
    assert not ok and "référence" in why
    ch = m.list()[0]
    ch.authorization_ref = "Convention n°7"
    m.save(ch)
    assert m.monitor_authorization(446.00625e6, 12_500, simulated=False, record=False)[0]
    ok, _, why = m.monitor_authorization(446.00625e6, 12_500, simulated=False, record=True)
    assert not ok and "enregistrement" in why
    ch.recording_allowed = True
    m.save(ch)
    assert m.monitor_authorization(446.00625e6, 12_500, simulated=False, record=True)[0]
    assert not m.monitor_authorization(446.02e6, 12_500, simulated=False, record=False)[0]  # hors canal


def test_engine_monitor_records_wav(db, tmp_path):
    sc = Scenario(emitters=[Emitter("fm_tone", FC + 30e3, -35)], noise_dbfs=-60)
    rx = SimulatedReceiver(sc, realtime=False)
    rx.open()
    rx.configure(ReceiverConfig(FC, FS, 30))
    eng = AcquisitionEngine(rx, db)
    chunks = []
    eng.on_audio = lambda a, open_: chunks.append((a, open_))
    with pytest.raises(ValueError):
        eng.start_monitor(FC + 200e3)
    wav_path = tmp_path / "rec.wav"
    eng.start_monitor(FC + 30e3, record_path=str(wav_path))
    eng.begin_session()
    for _ in range(20):
        eng.process_block(rx.read(eng.block_size))
    assert eng.stop_monitor() == str(wav_path)
    assert chunks and any(o for _, o in chunks)
    with wave.open(str(wav_path)) as w:
        assert w.getframerate() == 16000 and w.getnframes() > 16000
    eng.start_monitor(FC + 30e3)
    eng.retune(ReceiverConfig(FC + 1e6, FS, 30))  # le canal sort de la bande : écoute arrêtée
    assert eng.monitor is None
    actions = [a["action"] for a in db.list_audit()]
    assert "audio.monitor.start" in actions and "audio.monitor.stop" in actions
