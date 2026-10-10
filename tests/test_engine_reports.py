import time

import pytest

from lunatic_radio_lab.dsp.activity import ActivityParams
from lunatic_radio_lab.dsp.synth import preset_scenarios
from lunatic_radio_lab.drivers.simulated import SimulatedReceiver
from lunatic_radio_lab.engine import AcquisitionEngine
from lunatic_radio_lab.models import ReceiverConfig
from lunatic_radio_lab.reports import build_report, write_pdf_report, write_report_csv
from lunatic_radio_lab.selftest import reception_test, run_selftests


def make_engine(db, scen="intermittent", realtime=False):
    rx = SimulatedReceiver(preset_scenarios()[scen], realtime=realtime)
    rx.open()
    rx.configure(ReceiverConfig(446.1e6, 250e3, 30))
    return AcquisitionEngine(rx, db, 4096, ActivityParams()), rx


def test_engine_blocks_events_and_snapshot(db):
    eng, rx = make_engine(db)
    got = []
    eng.on_events = got.extend
    eng.begin_session()
    for _ in range(int(8 * 250e3 / eng.block_size)):
        eng.process_block(rx.read(eng.block_size))
    eng.end_session()
    evs = db.query_events()
    assert len(evs) >= 3 and got
    assert all(e.simulated for e in evs)
    assert any(e.classification and "FM analogique" in e.classification for e in evs)
    snap = eng.snapshot(1.0)
    assert snap.simulated and len(snap.iq) == pytest.approx(250e3, rel=0.05)
    assert eng.max_hold is not None and (eng.max_hold.power_dbfs >= eng.last_frame.power_dbfs).all()
    sub = eng.iq_between(snap.start_ts, snap.start_ts + 0.5)
    assert len(sub.iq) == pytest.approx(125e3, rel=0.02)


def test_engine_thread_start_stop_and_retune(db):
    eng, rx = make_engine(db, realtime=True)
    frames = []
    eng.on_frame = lambda f, d: frames.append(f)
    eng.start()
    time.sleep(0.6)
    eng.retune(ReceiverConfig(446.05e6, 250e3, 20))
    time.sleep(0.6)
    eng.stop()
    assert len(frames) > 5
    assert frames[-1].center_freq_hz == 446.05e6
    assert not eng.running
    assert db.list_sessions()[0]["end_ts"] is not None
    with pytest.raises(Exception):
        eng.retune(ReceiverConfig(5e9, 250e3, 20))


def test_reports_pdf_csv(db, tmp_path):
    eng, rx = make_engine(db, "canaux_occupes")
    eng.begin_session()
    for _ in range(int(3 * 250e3 / eng.block_size)):
        eng.process_block(rx.read(eng.block_size))
    eng.end_session()
    for r in run_selftests():
        db.add_test_result(r)
    db.log_error("test", "erreur de démonstration")
    data = build_report(db, spectrum=eng.max_hold, spectrum_is_max_hold=True, title="Test")
    assert data.contains_simulated and not data.contains_real
    assert data.events_simulated and not data.events_real
    assert len(data.tests) == 7 and data.errors
    pdf = write_pdf_report(data, tmp_path / "r.pdf")
    assert pdf.read_bytes()[:4] == b"%PDF" and pdf.stat().st_size > 5000
    ev, meta = write_report_csv(data, tmp_path / "r.csv")
    text = ev.read_text(encoding="utf-8-sig")
    assert "SIMULATION" in text and "frequence_emission_hz" in text
    mt = meta.read_text(encoding="utf-8-sig")
    assert "limite_technique" in mt and "contient_donnees_simulees;oui" in mt
    real_only = build_report(db, include_simulated=False)
    assert not real_only.events_simulated and not real_only.contains_simulated


def test_reception_test_simulated():
    rx = SimulatedReceiver(realtime=False)
    r = reception_test(rx, ReceiverConfig(446.1e6, 250e3, 30), 0.3)
    assert r.passed and r.simulated and r.details["echantillons"] == int(0.3 * 250e3)


def test_selftests_pass():
    assert all(r.passed for r in run_selftests())
