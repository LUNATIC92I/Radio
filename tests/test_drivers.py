import sys
import types

import numpy as np
import pytest

from lunatic_radio_lab.drivers import registry, soapy_driver, usb_scan
from lunatic_radio_lab.drivers.base import ReceiverError
from lunatic_radio_lab.drivers.iqfile import IQFileReceiver
from lunatic_radio_lab.drivers.simulated import SimulatedReceiver
from lunatic_radio_lab.dsp.spectrum import saturation_ratio
from lunatic_radio_lab.dsp.synth import Emitter, Scenario
from lunatic_radio_lab.iq_io import open_raw, read_sigmf, write_sigmf
from lunatic_radio_lab.models import ReceiverConfig


def test_simulated_receiver_validation_and_read():
    rx = SimulatedReceiver(realtime=False)
    rx.open()
    applied = rx.configure(ReceiverConfig(446.1e6, 250e3, 99.0))
    assert applied.gain_db == 60.0  # ramené dans la plage
    x = rx.read(4096)
    assert x.dtype == np.complex64 and len(x) == 4096
    with pytest.raises(ReceiverError):
        rx.configure(ReceiverConfig(10e9, 250e3, 30))
    errors, _ = rx.validate_config(ReceiverConfig(446e6, 10e6, 30))
    assert errors


def test_simulated_saturation_with_high_gain():
    rx = SimulatedReceiver(Scenario(emitters=[Emitter("carrier", 446.1e6 + 1e4, -10)]), realtime=False)
    rx.open()
    rx.configure(ReceiverConfig(446.1e6, 250e3, 30))
    assert saturation_ratio(rx.read(8192)) == 0
    rx.configure(ReceiverConfig(446.1e6, 250e3, 60))
    assert saturation_ratio(rx.read(8192)) > 0.01


def test_sigmf_roundtrip_and_replay(tmp_path):
    iq = (np.exp(2j * np.pi * 0.01 * np.arange(10_000)) * 0.5).astype(np.complex64)
    cap = write_sigmf(tmp_path / "cap", iq, 250e3, 446e6, simulated=True, description="test")
    back = read_sigmf(cap.data_path)
    assert back.simulated and back.sample_rate == 250e3 and back.center_freq == 446e6
    assert np.allclose(back.read(), iq)
    rx = IQFileReceiver(back, loop=True, realtime=False)
    rx.open()
    assert rx.simulated
    assert len(rx.read(25_000)) == 25_000  # boucle
    rx2 = IQFileReceiver(back, loop=False, realtime=False)
    rx2.open()
    rx2.read(9000)
    with pytest.raises(EOFError):
        rx2.read(5000)


def test_raw_formats(tmp_path):
    p = tmp_path / "x.cu8"
    np.array([255, 0, 127, 128] * 10, dtype=np.uint8).tofile(p)
    cap = open_raw(p, 1e6, 100e6, "cu8")
    x = cap.read()
    assert len(x) == 20 and x[0].real == pytest.approx(1.0) and x[0].imag == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        open_raw(p, 1e6, 100e6, "bogus")


class _Range:
    def __init__(self, a, b):
        self.a, self.b = a, b

    def minimum(self):
        return self.a

    def maximum(self):
        return self.b


class _SR:
    def __init__(self, ret):
        self.ret = ret


def fake_soapy(enum):
    m = types.ModuleType("SoapySDR")
    m.SOAPY_SDR_RX, m.SOAPY_SDR_TX, m.SOAPY_SDR_CF32 = 1, 0, "CF32"
    m.SOAPY_SDR_TIMEOUT, m.SOAPY_SDR_OVERFLOW = -1, -4
    calls = []

    class Device:
        def __init__(self, kw):
            self.kw = kw
            self.freq = 0
            self.rate = 0
            self.gain = 0

        @staticmethod
        def enumerate():
            return enum

        @staticmethod
        def unmake(d):
            pass

        def getNumChannels(self, d):
            return 1

        def getHardwareInfo(self):
            return {"product": "RTL2838UHIDIR", "manufacturer": "Realtek"}

        def getHardwareKey(self):
            return "RTLSDR"

        def getFrequencyRange(self, d, c):
            return [_Range(24e6, 1766e6)]

        def listSampleRates(self, d, c):
            return [250e3, 1.024e6, 2.4e6]

        def getGainRange(self, d, c):
            return _Range(0, 49.6)

        def listAntennas(self, d, c):
            return ["RX"]

        def setSampleRate(self, d, c, r):
            assert d == m.SOAPY_SDR_RX
            self.rate = r

        def getSampleRate(self, d, c):
            return self.rate

        def setFrequency(self, d, c, f):
            assert d == m.SOAPY_SDR_RX
            self.freq = f

        def getFrequency(self, d, c):
            return self.freq

        def setGainMode(self, d, c, auto):
            pass

        def setGain(self, d, c, g):
            self.gain = g

        def getGain(self, d, c):
            return self.gain

        def setupStream(self, d, fmt, ch):
            assert d == m.SOAPY_SDR_RX, "seuls les flux de réception sont autorisés"
            calls.append("setupStream")
            return object()

        def activateStream(self, s):
            pass

        def deactivateStream(self, s):
            pass

        def closeStream(self, s):
            pass

        def readStream(self, s, bufs, n, timeoutUs=0):
            k = min(n, 1000)
            bufs[0][:k] = 0.1
            return _SR(k)

    m.Device = Device
    m.calls = calls
    return m


def test_soapy_enumeration_and_rx_only(monkeypatch):
    enum = [{"driver": "rtlsdr", "label": "Generic RTL2832U", "serial": "0001"},
            {"driver": "remote", "remote": "tcp://10.0.0.2"}]
    mod = fake_soapy(enum)
    monkeypatch.setitem(sys.modules, "SoapySDR", mod)
    devs = soapy_driver.enumerate_soapy()
    assert len(devs) == 1  # le périphérique réseau est ignoré par défaut
    d = devs[0]
    assert d.manufacturer == "Realtek" and d.freq_ranges_hz == [(24e6, 1766e6)]
    assert d.gain_range_db == (0, 49.6) and d.sample_rates_hz[0] == 250e3
    assert len(soapy_driver.enumerate_soapy(allow_network=True)) == 2
    rx = soapy_driver.SoapyReceiver(d)
    rx.config = ReceiverConfig(446.1e6, 250e3, 30)
    rx.open()
    x = rx.read(4096)
    assert len(x) == 4096 and np.allclose(x, 0.1)
    assert rx.configure(ReceiverConfig(446.2e6, 250e3, 20)).center_freq_hz == 446.2e6
    rx.close()
    assert mod.calls == ["setupStream"]


def test_registry_without_drivers_has_simulation(monkeypatch):
    monkeypatch.setattr(usb_scan, "_scan_sysfs", lambda: [])
    monkeypatch.setattr(usb_scan, "_scan_pyusb", lambda: [])
    devs = registry.discover_devices()
    assert devs[-1].simulated and devs[-1].status_text.startswith("Simulation")


def test_usb_detection_without_driver(monkeypatch):
    monkeypatch.setattr(usb_scan, "_scan_sysfs", lambda: [(0x1D50, 0x6089, "abc", "1-1"), (0x046D, 0xC52B, "", "1-2")])
    monkeypatch.setattr(registry, "enumerate_soapy", lambda **k: [])
    devs = registry.discover_devices(include_simulation=False)
    assert len(devs) == 1
    hk = devs[0]
    assert hk.model == "HackRF One" and hk.tx_declared and not hk.driver_available
    assert "Pilote SDR absent" in hk.status_text or "pilote SDR absent" in hk.status_text
    with pytest.raises(ReceiverError):
        registry.create_receiver(hk)
