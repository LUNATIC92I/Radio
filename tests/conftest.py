import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def lrl_home(tmp_path, monkeypatch):
    home = tmp_path / "lrl_home"
    monkeypatch.setenv("LRL_HOME", str(home))
    return home


@pytest.fixture
def db():
    from lunatic_radio_lab.storage.database import Database

    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def access(db):
    from lunatic_radio_lab.security.access import AccessController

    a = AccessController(db)
    a.set_pin("123456")
    return a


@pytest.fixture
def unlocked(access):
    assert access.unlock("123456")
    return access


def gen(emitters, seconds=1.0, fs=250e3, fc=446.1e6, noise=-60.0, seed=3):
    from lunatic_radio_lab.dsp.synth import Scenario, SignalGenerator

    g = SignalGenerator(Scenario(emitters=emitters, noise_dbfs=noise, seed=seed), fs)
    return g.generate(int(seconds * fs), fc)


@pytest.fixture
def rng():
    return np.random.default_rng(0)
