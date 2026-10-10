import os

import pytest

from lunatic_radio_lab.models import ActivityEvent, TestResult
from lunatic_radio_lab.security.access import AccessController, AccessDenied, hash_pin, verify_pin
from lunatic_radio_lab.security.files import ImportRejected, sanitize_filename, secure_import, secure_import_sigmf
from lunatic_radio_lab.iq_io import write_sigmf


def test_pin_hashing():
    h = hash_pin("abcdef")
    assert "abcdef" not in h and verify_pin("abcdef", h) and not verify_pin("abcdeg", h)
    assert not verify_pin("x", "garbage")


def test_access_flow_and_audit(db):
    clock = [1000.0]
    a = AccessController(db, clock=lambda: clock[0])
    with pytest.raises(ValueError):
        a.set_pin("123")
    a.set_pin("secret1")
    with pytest.raises(AccessDenied):
        a.require("channels.edit")
    a.require("acquisition.start")  # non sensible
    assert a.unlock("secret1")
    a.require("channels.edit")
    clock[0] += 3600
    assert not a.unlocked
    for _ in range(5):
        assert not a.unlock("wrong!")
    with pytest.raises(AccessDenied):
        a.unlock("secret1")  # verrouillage après 5 échecs
    clock[0] += 61
    assert a.unlock("secret1")
    with pytest.raises(AccessDenied):
        a.set_pin("newpin1", "badpin")
    actions = [r["action"] for r in db.list_audit()]
    assert "admin.unlock" in actions and "channels.edit" in actions
    assert any(not r["success"] for r in db.list_audit())


def test_elevated_context(db):
    a = AccessController(db)
    with a.elevated("test"):
        a.require("channels.edit")
    with pytest.raises(AccessDenied):
        a.require("channels.edit")


def test_secure_import(tmp_path):
    from lunatic_radio_lab.dsp.audio import save_wav, synthetic_test_clip
    wav = save_wav(synthetic_test_clip(0.2), tmp_path / "mon fichier (1).wav")
    imp = secure_import(wav, "audio", tmp_path / "imports")
    assert imp.path.exists() and len(imp.sha256) == 64 and " " not in imp.path.name
    assert not os.access(imp.path, os.W_OK) or os.geteuid() == 0
    fake = tmp_path / "fake.wav"
    fake.write_bytes(b"not a wav file at all")
    with pytest.raises(ImportRejected):
        secure_import(fake, "audio", tmp_path / "imports")
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(ImportRejected):
        secure_import(exe, "audio", tmp_path / "imports")
    link = tmp_path / "link.wav"
    link.symlink_to(wav)
    with pytest.raises(ImportRejected):
        secure_import(link, "audio", tmp_path / "imports")
    empty = tmp_path / "e.wav"
    empty.write_bytes(b"")
    with pytest.raises(ImportRejected):
        secure_import(empty, "audio", tmp_path / "imports")
    bad = tmp_path / "b.json"
    bad.write_text("{oops")
    with pytest.raises(ImportRejected):
        secure_import(bad, "json", tmp_path / "imports")
    assert sanitize_filename("../../etc/passwd") == "passwd"


def test_secure_import_sigmf(tmp_path):
    import numpy as np
    write_sigmf(tmp_path / "c", np.zeros(100, np.complex64), 1e5, 1e8, True)
    imp = secure_import_sigmf(tmp_path / "c.sigmf-meta", tmp_path / "imp")
    assert imp.path.exists() and imp.path.with_suffix(".sigmf-data").exists()


def test_database_roundtrip(db):
    db.set_setting("k", {"a": 1})
    assert db.get_setting("k") == {"a": 1} and db.get_setting("missing", 5) == 5
    sid = db.start_session("sim:0", "Sim", True, {"center_freq_hz": 1e6, "sample_rate_hz": 1e5}, {"x": 1})
    ev = ActivityEvent("sim:0", 1e6, 1.01e6, 10.0, 12.5, -30, -33, 20, 5000, 3.0, {"p": 1}, True, "CH1", 1.01e6, 5)
    db.add_event(ev, sid)
    db.end_session(sid)
    got = db.query_events()
    assert len(got) == 1 and got[0].duration_s == 2.5 and got[0].simulated and got[0].channel_name == "CH1"
    assert db.query_events(simulated=False) == []
    assert db.query_events(min_freq=2e6) == []
    db.update_event_classification(got[0].id, "FM", 0.8)
    assert db.query_events()[0].classification == "FM"
    db.add_test_result(TestResult("t", True, {"x": 1}, True))
    assert db.list_test_results()[0].passed
    db.log_error("src", "msg")
    assert db.list_errors()[0]["message"] == "msg"
    assert db.list_sessions()[0]["end_ts"] is not None
    assert db.purge_events() == 1


def test_database_file(tmp_path):
    from lunatic_radio_lab.storage.database import Database
    d = Database(tmp_path / "x.sqlite3")
    d.set_setting("a", 1)
    d.close()
    assert Database(tmp_path / "x.sqlite3").get_setting("a") == 1


def test_database_migration_adds_overlap_column(tmp_path):
    import sqlite3
    from lunatic_radio_lab.storage.database import Database
    p = tmp_path / "old.sqlite3"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, receiver_id TEXT, tuned_freq_hz REAL, "
                "emission_freq_hz REAL, channel_name TEXT, channel_freq_hz REAL, start_ts REAL, end_ts REAL, "
                "duration_s REAL, peak_power_dbfs REAL, mean_power_dbfs REAL, snr_db REAL, bandwidth_hz REAL, "
                "freq_std_hz REAL, frames INTEGER, detection_json TEXT, simulated INTEGER, classification TEXT, "
                "classification_confidence REAL, kind TEXT, session_id INTEGER)")
    con.execute("INSERT INTO events VALUES (1,'r',1,1,NULL,NULL,0,1,1,0,0,0,NULL,0,1,'{}',1,NULL,NULL,'k',NULL)")
    con.commit()
    con.close()
    d = Database(p)
    ev = d.query_events()[0]
    assert ev.overlap_suspected is False
    ev.overlap_suspected = True
    d.add_event(ev)
    assert any(e.overlap_suspected for e in d.query_events())
