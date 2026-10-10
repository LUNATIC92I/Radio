"""Moteur d'acquisition : récepteur → spectre → détection d'activité → stockage.

Indépendant de l'interface graphique (rappels Python) ; l'interface l'enveloppe
dans un adaptateur Qt. L'horodatage est dérivé du compteur d'échantillons
(début de session + n/fs), ce qui donne des durées cohérentes en simulation
accélérée comme en temps réel.
"""

from __future__ import annotations

import collections
import dataclasses
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .dsp.activity import ActivityDetector, ActivityParams
from .dsp.classifier import classify_iq
from .dsp.spectrum import SpectrumAnalyzer
from .drivers.base import Receiver, ReceiverError
from .models import ActivityEvent, Detection, ReceiverConfig, SpectrumFrame
from .storage.database import Database

log = logging.getLogger(__name__)


@dataclass
class IQSnapshot:
    iq: np.ndarray
    sample_rate: float
    center_freq: float
    start_ts: float
    simulated: bool
    receiver_id: str


class AcquisitionEngine:
    def __init__(
        self,
        receiver: Receiver,
        db: Database | None = None,
        fft_size: int = 4096,
        activity: ActivityParams | None = None,
        ring_seconds: float = 4.0,
        auto_classify: bool = True,
        scenario_name: str | None = None,
    ):
        self.receiver = receiver
        self.db = db
        self.analyzer = SpectrumAnalyzer(fft_size=fft_size)
        self.detector = ActivityDetector(activity or ActivityParams(), receiver.info.device_id, receiver.simulated)
        self.ring_seconds = ring_seconds
        self.auto_classify = auto_classify
        self.scenario_name = scenario_name
        self.session_id: int | None = None
        self.on_frame: Callable[[SpectrumFrame, list[Detection]], None] | None = None
        self.on_events: Callable[[list[ActivityEvent]], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self.on_status: Callable[[str], None] | None = None
        self._ring: collections.deque[tuple[float, np.ndarray]] = collections.deque()
        self._ring_n = 0
        self._ring_lock = threading.Lock()
        self._pending_cfg: ReceiverConfig | None = None
        self._pending_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._t0 = 0.0
        self._samples = 0
        self.frames = 0
        self.last_frame: SpectrumFrame | None = None
        self.max_hold: SpectrumFrame | None = None
        self.events_total = 0
        self.errors: list[str] = []

    # ---------------------------------------------------------------- paramètres
    @property
    def config(self) -> ReceiverConfig:
        return self.receiver.config

    @property
    def block_size(self) -> int:
        fs = self.receiver.config.sample_rate_hz
        n = max(self.analyzer.fft_size * 4, int(fs / 20))
        return int(2 ** np.ceil(np.log2(n)))

    def set_activity_params(self, params: ActivityParams) -> None:
        closed = self.detector.flush()
        self._store_events(closed)
        self.detector.params = params

    def retune(self, cfg: ReceiverConfig) -> None:
        """Changement de configuration appliqué entre deux lectures (thread-safe)."""
        errors, _ = self.receiver.validate_config(cfg)
        if errors:
            raise ReceiverError(" ".join(errors))
        with self._pending_lock:
            self._pending_cfg = cfg
        if not self.running:
            self._apply_pending()

    def _apply_pending(self) -> None:
        with self._pending_lock:
            cfg, self._pending_cfg = self._pending_cfg, None
        if cfg is None:
            return
        closed = self.detector.flush()
        self._store_events(closed)
        applied = self.receiver.configure(cfg)
        self.analyzer.reset()
        self.max_hold = None
        with self._ring_lock:
            self._ring.clear()
            self._ring_n = 0
        if self.db is not None:
            self.db.audit("opérateur", "receiver.configure", applied.to_dict())
        self._status(f"Configuration appliquée : {applied.center_freq_hz / 1e6:.4f} MHz, "
                     f"{applied.sample_rate_hz / 1e3:.0f} kS/s, gain {applied.gain_db if applied.gain_db is not None else 'auto'}")

    # ---------------------------------------------------------------- cycle de vie
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def begin_session(self) -> None:
        self._t0 = time.time()
        self._samples = 0
        if self.db is not None:
            self.session_id = self.db.start_session(
                self.receiver.info.device_id, self.receiver.info.label, self.receiver.simulated,
                self.receiver.config.to_dict(), self.detector.params.to_dict(), self.receiver.info.to_dict(),
                self.scenario_name,
            )

    def end_session(self) -> list[ActivityEvent]:
        closed = self.detector.flush()
        if self.auto_classify:
            for ev in closed:
                self._classify_event(ev)
        self._store_events(closed)
        if self.db is not None and self.session_id is not None:
            self.db.end_session(self.session_id)
        return closed

    def start(self) -> None:
        if self.running:
            return
        if not self.receiver.is_open:
            self.receiver.open()
        self._apply_pending()
        self.receiver.configure(self.receiver.config)
        self.begin_session()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lrl-acquisition", daemon=True)
        self._thread.start()
        self._status("Acquisition démarrée" + (" (SIMULATION)" if self.receiver.simulated else ""))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        closed = self.end_session()
        if closed and self.on_events:
            self.on_events(closed)
        try:
            self.receiver.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("Fermeture du récepteur : %s", exc)
        self._status("Acquisition arrêtée")

    def _run(self) -> None:
        consecutive_errors = 0
        while not self._stop.is_set():
            try:
                self._apply_pending()
                iq = self.receiver.read(self.block_size)
                consecutive_errors = 0
            except EOFError:
                self._status("Fin du fichier IQ")
                break
            except Exception as exc:  # noqa: BLE001
                consecutive_errors += 1
                self._error(f"Lecture du récepteur : {exc}")
                if consecutive_errors >= 5:
                    self._error("Acquisition interrompue après 5 erreurs consécutives.")
                    break
                time.sleep(0.2)
                continue
            try:
                self.process_block(iq)
            except Exception as exc:  # noqa: BLE001
                log.exception("Erreur de traitement")
                self._error(f"Traitement du signal : {exc}")

    # ---------------------------------------------------------------- traitement
    def process_block(self, iq: np.ndarray) -> tuple[SpectrumFrame, list[Detection], list[ActivityEvent]]:
        cfg = self.receiver.config
        if self._t0 == 0.0:
            self._t0 = time.time()
        start_ts = self._t0 + self._samples / cfg.sample_rate_hz
        self._samples += len(iq)
        ts = self._t0 + self._samples / cfg.sample_rate_hz
        with self._ring_lock:
            self._ring.append((start_ts, iq))
            self._ring_n += len(iq)
            limit = int(self.ring_seconds * cfg.sample_rate_hz)
            while self._ring_n - len(self._ring[0][1]) >= limit and len(self._ring) > 1:
                self._ring_n -= len(self._ring.popleft()[1])
        frame = self.analyzer.process(iq, cfg.center_freq_hz, cfg.sample_rate_hz, self.receiver.info.device_id,
                                      self.receiver.simulated, cfg.gain_db, ts)
        closed, dets = self.detector.update(frame)
        self.frames += 1
        self.last_frame = frame
        self._update_max_hold(frame)
        if self.on_frame:
            self.on_frame(frame, dets)
        if closed:
            if self.auto_classify:
                for ev in closed:
                    self._classify_event(ev)
            self._store_events(closed)
            if self.on_events:
                self.on_events(closed)
        return frame, dets, closed

    def _update_max_hold(self, frame: SpectrumFrame) -> None:
        mh = self.max_hold
        if mh is None or mh.power_dbfs.shape != frame.power_dbfs.shape or mh.center_freq_hz != frame.center_freq_hz:
            self.max_hold = dataclasses.replace(frame, power_dbfs=frame.power_dbfs.copy())
            return
        np.maximum(mh.power_dbfs, frame.power_dbfs, out=mh.power_dbfs)
        mh.saturated = mh.saturated or frame.saturated
        mh.saturation_ratio = max(mh.saturation_ratio, frame.saturation_ratio)
        mh.timestamp = frame.timestamp
        mh.noise_floor_dbfs = frame.noise_floor_dbfs

    def reset_max_hold(self) -> None:
        self.max_hold = None

    def _classify_event(self, ev: ActivityEvent) -> None:
        snap = self.iq_between(ev.start_ts, ev.end_ts)
        if snap is None or len(snap.iq) < 0.1 * snap.sample_rate:
            return
        bw = max(12_500.0, 1.5 * (ev.bandwidth_hz or 0.0))
        bw = min(bw, 0.8 * snap.sample_rate)
        try:
            c = classify_iq(snap.iq, snap.sample_rate, ev.emission_freq_hz - snap.center_freq, snap.center_freq, bw,
                            simulated=snap.simulated)
        except Exception as exc:  # noqa: BLE001
            log.info("Classification impossible : %s", exc)
            return
        b = c.best
        if b is not None:
            ev.classification = b.name if b.confidence >= 0.5 else "Non identifié"
            ev.classification_confidence = round(b.confidence, 3)

    def _store_events(self, events: list[ActivityEvent]) -> None:
        self.events_total += len(events)
        if self.db is None:
            return
        for ev in events:
            self.db.add_event(ev, self.session_id)

    # ---------------------------------------------------------------- captures IQ
    def snapshot(self, seconds: float | None = None) -> IQSnapshot | None:
        cfg = self.receiver.config
        with self._ring_lock:
            if not self._ring:
                return None
            start = self._ring[0][0]
            iq = np.concatenate([b for _, b in self._ring])
        if seconds is not None:
            n = int(seconds * cfg.sample_rate_hz)
            if len(iq) > n:
                start += (len(iq) - n) / cfg.sample_rate_hz
                iq = iq[-n:]
        return IQSnapshot(iq, cfg.sample_rate_hz, cfg.center_freq_hz, start, self.receiver.simulated,
                          self.receiver.info.device_id)

    def iq_between(self, t0: float, t1: float) -> IQSnapshot | None:
        snap = self.snapshot()
        if snap is None:
            return None
        fs = snap.sample_rate
        i0 = max(0, int((t0 - snap.start_ts) * fs))
        i1 = min(len(snap.iq), int((t1 - snap.start_ts) * fs))
        if i1 - i0 <= 0:
            return None
        return IQSnapshot(snap.iq[i0:i1], fs, snap.center_freq, snap.start_ts + i0 / fs, snap.simulated,
                          snap.receiver_id)

    # ---------------------------------------------------------------- notifications
    def _status(self, msg: str) -> None:
        log.info(msg)
        if self.on_status:
            self.on_status(msg)

    def _error(self, msg: str) -> None:
        log.error(msg)
        self.errors.append(msg)
        if self.db is not None:
            self.db.log_error("acquisition", msg, self.session_id)
        if self.on_error:
            self.on_error(msg)
