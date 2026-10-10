import pytest

from lunatic_radio_lab.dsp.activity import ActivityDetector, ActivityParams, ChannelWindow
from lunatic_radio_lab.dsp.spectrum import SpectrumAnalyzer
from lunatic_radio_lab.dsp.synth import Emitter, Scenario, SignalGenerator

FC, FS, BLK = 446.1e6, 250e3, 8192


def run(scenario, seconds, params=None):
    g = SignalGenerator(scenario, FS)
    sa = SpectrumAnalyzer(4096)
    det = ActivityDetector(params or ActivityParams(), "sim:0", True)
    events = []
    t = 0.0
    for _ in range(int(seconds * FS / BLK)):
        t += BLK / FS
        ev, _ = det.update(sa.process(g.generate(BLK, FC), FC, FS, timestamp=t))
        events += ev
    events += det.flush()
    return events, det


def test_intermittent_emission_durations():
    sc = Scenario(emitters=[Emitter("fm_voice", FC + 20_000, -40.0, on_s=1.0, off_s=1.0, phase_s=0.0)])
    events, _ = run(sc, 6.2)
    assert len(events) == 3
    for e in events:
        assert e.duration_s == pytest.approx(1.0, abs=0.1)
        assert e.emission_freq_hz == pytest.approx(FC + 20_000, abs=500)
        assert e.simulated and e.receiver_id == "sim:0"
        assert e.kind == "émission détectée"
        assert e.detection_params["open_threshold_db"] == 10.0


def test_short_spikes_rejected_by_persistence_and_min_duration():
    sc = Scenario(emitters=[Emitter("carrier", FC + 20_000, -40.0, on_s=0.03, off_s=0.5)])
    events, det = run(sc, 3.0, ActivityParams(persistence_frames=3, min_duration_s=0.2))
    assert events == []
    assert det.false_alarm_rejected > 0


def test_hang_time_bridges_short_gaps():
    sc = Scenario(emitters=[Emitter("carrier", FC + 20_000, -40.0, on_s=0.8, off_s=0.15)])
    merged, _ = run(sc, 4.0, ActivityParams(hang_time_s=0.4))
    split, _ = run(sc, 4.0, ActivityParams(hang_time_s=0.05))
    assert len(merged) < len(split)


def test_channel_filter_and_labelling():
    sc = Scenario(emitters=[Emitter("carrier", 446.00625e6, -40.0), Emitter("carrier", FC + 60_000, -40.0)])
    params = ActivityParams(channels=[ChannelWindow("CH1", 446.00625e6, 12_500)], channels_only=True)
    events, _ = run(sc, 1.0, params)
    assert len(events) == 1
    assert events[0].channel_name == "CH1"
    assert events[0].configured_freq_hz == 446.00625e6


def test_noise_only_no_events():
    events, _ = run(Scenario(noise_dbfs=-50.0), 3.0)
    assert events == []


def test_peak_not_below_mean():
    sc = Scenario(emitters=[Emitter("fm_voice", FC, -40.0, fading_depth_db=10, fading_rate_hz=1.0)])
    events, _ = run(sc, 3.0)
    assert events and all(e.peak_power_dbfs >= e.mean_power_dbfs - 1e-6 for e in events)
