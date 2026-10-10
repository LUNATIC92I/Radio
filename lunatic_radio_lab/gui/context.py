"""Contexte applicatif partagé par les écrans : base, accès, canaux, récepteur, moteur."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, Signal

from .. import paths
from ..channels import ChannelManager
from ..dsp.activity import ActivityParams
from ..dsp.synth import Scenario, preset_scenarios
from ..drivers.base import Receiver, ReceiverError
from ..drivers.iqfile import IQFileReceiver
from ..drivers.registry import create_receiver
from ..drivers.simulated import SimulatedReceiver, simulated_device_info
from ..engine import AcquisitionEngine
from ..models import ActivityEvent, DeviceInfo, Detection, ReceiverConfig, SpectrumFrame
from ..security.access import AccessController
from ..storage.database import Database

log = logging.getLogger(__name__)


class QtLogHandler(logging.Handler):
    def __init__(self, ctx: AppContext):
        super().__init__(logging.INFO)
        self.ctx = ctx
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s : %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.ctx.log_line.emit(self.format(record), record.levelno)
        except RuntimeError:
            pass


class AppContext(QObject):
    frame = Signal(object, object)  # SpectrumFrame, list[Detection]
    events_closed = Signal(object)  # list[ActivityEvent]
    status = Signal(str)
    error = Signal(str)
    notify = Signal(str, str)  # message, niveau (info|ok|warn|error)
    acquisition_changed = Signal(bool)
    receiver_changed = Signal(object)  # DeviceInfo
    channels_changed = Signal()
    access_changed = Signal(bool)
    history_changed = Signal()
    log_line = Signal(str, int)
    scenario_changed = Signal(object)

    def __init__(self, db: Database | None = None):
        super().__init__()
        self.db = db or Database(paths.database_path())
        self.access = AccessController(self.db)
        self.channels = ChannelManager(self.db, self.access)
        self.device: DeviceInfo = simulated_device_info()
        self.scenario: Scenario = preset_scenarios()["intermittent"]
        self.receiver: Receiver = SimulatedReceiver(self.scenario)
        cfg = self.db.get_setting("receiver_config")
        self.receiver.config = ReceiverConfig(**cfg) if cfg else ReceiverConfig()
        self.activity_params = self._load_activity_params()
        self.fft_size: int = int(self.db.get_setting("fft_size", 4096))
        self.engine: AcquisitionEngine | None = None
        self.last_frame: SpectrumFrame | None = None
        self.last_detections: list[Detection] = []
        self.session_events: list[ActivityEvent] = []
        self._log_handler = QtLogHandler(self)
        logging.getLogger().addHandler(self._log_handler)
        self.error.connect(lambda m: self.notify.emit(m, "error"))

    # ------------------------------------------------------------------ paramètres
    def _load_activity_params(self) -> ActivityParams:
        d = self.db.get_setting("activity_params") or {}
        p = ActivityParams()
        for k, v in d.items():
            if hasattr(p, k) and k not in ("channels",):
                setattr(p, k, float("inf") if (k == "max_bandwidth_hz" and v is None) else v)
        p.channels = self.channels.windows()
        return p

    def save_activity_params(self, p: ActivityParams) -> None:
        p.channels = self.channels.windows()
        self.activity_params = p
        d = p.to_dict()
        d.pop("channels", None)
        d.pop("close_threshold_db", None)
        self.db.set_setting("activity_params", d)
        self.db.audit(self.access.actor, "detection.params", d)
        if self.engine is not None:
            self.engine.set_activity_params(p)
        self.notify.emit("Paramètres de détection appliqués.", "ok")

    def refresh_channel_windows(self) -> None:
        self.activity_params.channels = self.channels.windows()
        if self.engine is not None:
            self.engine.detector.params.channels = self.activity_params.channels
        self.channels_changed.emit()

    @property
    def calibration_offset_db(self) -> float | None:
        return self.db.get_setting("calibration_offset_db")

    @property
    def power_unit(self) -> str:
        return "dBm (étalonné)" if self.calibration_offset_db is not None else "dBFS"

    def to_display_power(self, dbfs: float) -> float:
        off = self.calibration_offset_db
        return dbfs + off if off is not None else dbfs

    # ------------------------------------------------------------------ récepteur
    @property
    def running(self) -> bool:
        return self.engine is not None and self.engine.running

    @property
    def simulated(self) -> bool:
        return self.receiver.simulated

    def select_device(self, info: DeviceInfo) -> None:
        if self.running:
            self.stop_acquisition()
        rx = SimulatedReceiver(self.scenario) if info.backend == "simulation" else create_receiver(info)
        old_cfg = self.receiver.config
        self.receiver = rx
        self.device = info
        errors, _ = rx.validate_config(old_cfg)
        if not errors:
            rx.config = old_cfg
        else:
            lo = info.freq_ranges_hz[0][0] if info.freq_ranges_hz else old_cfg.center_freq_hz
            rate = info.sample_rates_hz[0] if info.sample_rates_hz else old_cfg.sample_rate_hz
            rx.config = ReceiverConfig(center_freq_hz=max(lo, old_cfg.center_freq_hz), sample_rate_hz=rate)
        self.db.audit(self.access.actor, "receiver.select", {"device": info.device_id, "label": info.label})
        self.receiver_changed.emit(info)
        self.notify.emit(f"Récepteur sélectionné : {info.label}", "info")

    def use_iq_file(self, receiver: IQFileReceiver) -> None:
        if self.running:
            self.stop_acquisition()
        self.receiver = receiver
        self.device = receiver.info
        self.db.audit(self.access.actor, "receiver.iqfile", {"file": str(receiver.capture.data_path)})
        self.receiver_changed.emit(receiver.info)

    def set_scenario(self, scen: Scenario) -> None:
        self.scenario = scen
        if isinstance(self.receiver, SimulatedReceiver):
            self.receiver.set_scenario(scen)
        self.db.audit(self.access.actor, "lab.scenario", {"name": scen.name, "emitters": len(scen.emitters)})
        self.scenario_changed.emit(scen)

    def apply_config(self, cfg: ReceiverConfig) -> None:
        errors, warnings = self.receiver.validate_config(cfg)
        if errors:
            raise ReceiverError(" ".join(errors))
        for w in warnings:
            self.notify.emit(w, "warn")
        if self.engine is not None and self.running:
            self.engine.retune(cfg)
        else:
            self.receiver.config = cfg
        self.db.set_setting("receiver_config", cfg.to_dict())

    def set_fft_size(self, n: int) -> None:
        self.fft_size = n
        self.db.set_setting("fft_size", n)
        if self.engine is not None:
            self.engine.analyzer.fft_size = n
            self.engine.analyzer.reset()
            self.engine.reset_max_hold()

    def start_acquisition(self) -> bool:
        if self.running:
            return True
        self.activity_params.channels = self.channels.windows()
        eng = AcquisitionEngine(self.receiver, self.db, self.fft_size, self.activity_params,
                                scenario_name=self.scenario.name if self.simulated else None)
        eng.on_frame = self._on_frame
        eng.on_events = self._on_events
        eng.on_error = self.error.emit
        eng.on_status = self.status.emit
        try:
            eng.start()
        except Exception as exc:  # noqa: BLE001
            msg = f"Démarrage impossible : {exc}"
            self.db.log_error("acquisition", msg)
            self.error.emit(msg)
            return False
        self.engine = eng
        self.session_events = []
        self.db.audit(self.access.actor, "acquisition.start",
                      {"device": self.device.device_id, "config": self.receiver.config.to_dict()})
        self.acquisition_changed.emit(True)
        return True

    def stop_acquisition(self) -> None:
        if self.engine is None:
            return
        self.engine.stop()
        self.db.audit(self.access.actor, "acquisition.stop", {"frames": self.engine.frames,
                                                              "events": self.engine.events_total})
        self.acquisition_changed.emit(False)
        self.history_changed.emit()

    def _on_frame(self, frame: SpectrumFrame, dets: list[Detection]) -> None:
        self.last_frame = frame
        self.last_detections = dets
        self.frame.emit(frame, dets)

    def _on_events(self, events: list[ActivityEvent]) -> None:
        self.session_events.extend(events)
        self.events_closed.emit(events)
        self.history_changed.emit()

    def shutdown(self) -> None:
        try:
            self.stop_acquisition()
        finally:
            logging.getLogger().removeHandler(self._log_handler)
            self.db.audit(self.access.actor, "app.quit", {"ts": time.time()})
