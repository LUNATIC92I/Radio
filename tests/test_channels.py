import pytest

from lunatic_radio_lab.channels import AuthorizedChannel, ChannelManager, validate_channel
from lunatic_radio_lab.drivers.simulated import simulated_device_info
from lunatic_radio_lab.security.access import AccessDenied


def test_validation_rules():
    ok = AuthorizedChannel("Lab 1", 433.5e6, 12_500, authorization_ref="Labo n°1")
    rep = validate_channel(ok)
    assert rep.ok and any("réglementaire" in w for w in rep.warnings)
    assert not validate_channel(AuthorizedChannel("", 433.5e6, 12_500)).ok
    assert not validate_channel(AuthorizedChannel("x", 1.0, 12_500)).ok
    assert not validate_channel(AuthorizedChannel("x", 433e6, 10.0)).ok
    assert not validate_channel(AuthorizedChannel("x", 433e6, 12_500, recording_allowed=True)).ok
    dup = validate_channel(AuthorizedChannel("lab 1", 434e6, 12_500), [ok])
    assert not dup.ok
    over = validate_channel(AuthorizedChannel("Lab 2", 433.505e6, 12_500), [ok])
    assert any("Chevauchement" in w for w in over.warnings)
    far = validate_channel(AuthorizedChannel("SHF", 5.8e9, 20e6, authorization_ref="x"), device=simulated_device_info())
    assert any("capacités" in w for w in far.warnings)
    pmr = validate_channel(AuthorizedChannel("P", 446.00625e6, 12_500, profile_id="pmr446_analog"))
    assert any("PMR446" in w for w in pmr.warnings)


def test_manager_requires_admin(db, access):
    m = ChannelManager(db, access)
    ch = AuthorizedChannel("Lab", 433.5e6, 12_500, authorization_ref="ref")
    with pytest.raises(AccessDenied):
        m.save(ch)
    access.unlock("123456")
    assert m.save(ch).ok and ch.id
    assert m.channel_at(433.5e6).name == "Lab"
    assert m.recording_permitted(433.495e6, 433.505e6) is None
    ch.recording_allowed = True
    assert m.save(ch).ok
    assert m.recording_permitted(433.495e6, 433.505e6).name == "Lab"
    assert m.recording_permitted(433.0e6, 434e6) is None
    assert m.import_pmr446() == 16 and m.import_pmr446() == 0
    js = m.export_json()
    csv_text = m.export_csv()
    assert "PMR446 CH16" in js and "PMR446 CH01" in csv_text
    m.delete(ch.id)
    assert m.get(ch.id) is None
    access.lock()
    with pytest.raises(AccessDenied):
        m.delete(m.list()[0].id)


def test_import_records(db, unlocked):
    m = ChannelManager(db, unlocked)
    ok, problems = m.import_records([
        {"name": "A", "center_freq_hz": "433500000", "bandwidth_hz": "12500", "recording_allowed": "false"},
        {"name": "B", "center_freq_hz": "abc", "bandwidth_hz": "1"},
        {"name": "", "center_freq_hz": 1e8, "bandwidth_hz": 12500},
    ])
    assert ok == 1 and len(problems) == 2
