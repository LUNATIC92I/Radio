import pytest

pytest.importorskip("PySide6")
pytestqt = pytest.importorskip("pytestqt")


@pytest.fixture
def window(qtbot, lrl_home):
    from lunatic_radio_lab.gui.app import create_app
    from lunatic_radio_lab.gui.context import AppContext
    from lunatic_radio_lab.gui.main_window import MainWindow
    create_app()
    ctx = AppContext()
    w = MainWindow(ctx)
    qtbot.addWidget(w)
    w.show()
    yield w
    ctx.stop_acquisition()


def test_all_pages_and_acquisition(window, qtbot):
    ctx = window.ctx
    assert len(window.pages) == 14
    assert ctx.start_acquisition()
    qtbot.waitUntil(lambda: ctx.last_frame is not None, timeout=5000)
    for i in range(len(window.pages)):
        window.nav.setCurrentRow(i)
        qtbot.wait(150)
    assert ctx.last_frame.simulated
    ctx.stop_acquisition()
    assert not ctx.running


def test_console_commands(window):
    from lunatic_radio_lab.gui.pages.console import ConsolePage
    con = next(p for p in window.pages if isinstance(p, ConsolePage))
    assert any("Commandes" in l for l in con.execute("help"))
    assert "Appliqué" in con.execute("tune 446.05")[0]
    assert window.ctx.receiver.config.center_freq_hz == 446.05e6
    assert "inconnue" in con.execute("rm -rf /")[0]
    assert con.execute("selftest")


def test_protected_channel_save_refused_when_locked(window, monkeypatch):
    from lunatic_radio_lab.gui.pages import channels as chp
    page = next(p for p in window.pages if isinstance(p, chp.ChannelsPage))
    window.ctx.access.set_pin("123456")
    monkeypatch.setattr(chp, "guarded", lambda ctx, parent, fn: None)  # l'utilisateur annule le déverrouillage
    page.name.setText("Lab")
    page.auth.setText("ref")
    page.save()
    assert window.ctx.channels.list() == []
    window.ctx.access.unlock("123456")
    monkeypatch.setattr(chp, "guarded", lambda ctx, parent, fn: fn())
    page.save()
    assert [c.name for c in window.ctx.channels.list()] == ["Lab"]


def test_lab_scenario_apply(window):
    from lunatic_radio_lab.gui.pages.lab import LabPage
    lab = next(p for p in window.pages if isinstance(p, LabPage))
    lab.preset.setCurrentIndex(lab.preset.findData("collision"))
    lab.load_preset()
    lab.apply()
    assert window.ctx.scenario.name == "Collision de transmissions"


def test_live_monitor_in_simulation(window, qtbot):
    ctx = window.ctx
    got = []
    ctx.audio_chunk.connect(lambda a, o: got.append(len(a)))
    with pytest.raises(RuntimeError):
        ctx.start_monitor(446.00625e6)  # acquisition non démarrée
    assert ctx.start_acquisition()
    qtbot.waitUntil(lambda: ctx.last_frame is not None, timeout=5000)
    ctx.start_monitor(446.00625e6)
    qtbot.waitUntil(lambda: len(got) > 3, timeout=5000)
    ctx.stop_monitor()
    assert ctx.engine.monitor is None
