"""Moteur de détection d'activité radio (événements début/fin).

Anti-fausses alertes :
  * seuil d'ouverture et seuil de maintien (hystérésis) ;
  * persistance : N trames consécutives au-dessus du seuil d'ouverture ;
  * durée minimale d'un événement ;
  * temps de maintien (« hang time ») qui tolère de courtes coupures ;
  * filtres de largeur de bande et filtre de canaux autorisés.

Un événement signifie « une émission a été détectée », jamais « un talkie-walkie a
été identifié ». La caractérisation éventuelle est faite par le module
``classifier`` avec un niveau de confiance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from ..models import ActivityEvent, Detection, SpectrumFrame
from .detection import DetectionParams, detect_emissions
from .spectrum import from_db, to_db


@dataclass
class ChannelWindow:
    name: str
    center_hz: float
    bandwidth_hz: float

    @property
    def low(self) -> float:
        return self.center_hz - self.bandwidth_hz / 2

    @property
    def high(self) -> float:
        return self.center_hz + self.bandwidth_hz / 2


@dataclass
class ActivityParams:
    open_threshold_db: float = 10.0
    hysteresis_db: float = 4.0
    persistence_frames: int = 2
    min_duration_s: float = 0.2
    hang_time_s: float = 0.4
    freq_tolerance_hz: float = 6_250.0
    min_bandwidth_hz: float = 0.0
    max_bandwidth_hz: float = float("inf")
    dc_exclude_hz: float = 0.0
    merge_gap_hz: float = 2_000.0
    channels_only: bool = False
    channels: list[ChannelWindow] = field(default_factory=list)

    @property
    def close_threshold_db(self) -> float:
        return max(1.0, self.open_threshold_db - self.hysteresis_db)

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["max_bandwidth_hz"] == float("inf"):
            d["max_bandwidth_hz"] = None
        d["close_threshold_db"] = self.close_threshold_db
        d["channels"] = [c["name"] for c in d["channels"]]
        return d


@dataclass
class _Track:
    start_ts: float
    last_ts: float
    freqs: list[float]
    peak_db: float
    pow_lin: list[float]
    snrs: list[float]
    bws: list[float]
    consecutive_open: int
    active: bool
    channel: ChannelWindow | None
    tuned_freq_hz: float
    frames: int = 0

    @property
    def freq(self) -> float:
        return float(np.median(self.freqs[-50:]))


class ActivityDetector:
    def __init__(self, params: ActivityParams | None = None, receiver_id: str = "", simulated: bool = False):
        self.params = params or ActivityParams()
        self.receiver_id = receiver_id
        self.simulated = simulated
        self._tracks: list[_Track] = []
        self.false_alarm_rejected = 0  # candidats écartés (persistance ou durée insuffisante)

    def reset(self) -> None:
        self._tracks.clear()

    @property
    def open_tracks(self) -> list[_Track]:
        return [t for t in list(self._tracks) if t.active]

    def tracks_snapshot(self) -> list[_Track]:
        """Copie des pistes (candidates et confirmées), sûre pour un affichage depuis un autre thread."""
        return list(self._tracks)

    def _channel_for(self, det: Detection) -> ChannelWindow | None:
        for ch in self.params.channels:
            if ch.low <= det.center_freq_hz <= ch.high:
                return ch
        return None

    def _det_params(self) -> DetectionParams:
        p = self.params
        return DetectionParams(
            threshold_db=p.close_threshold_db,
            merge_gap_hz=p.merge_gap_hz,
            dc_exclude_hz=p.dc_exclude_hz,
            min_bandwidth_hz=p.min_bandwidth_hz,
            max_bandwidth_hz=p.max_bandwidth_hz,
        )

    def update(self, frame: SpectrumFrame) -> tuple[list[ActivityEvent], list[Detection]]:
        """Traite une trame ; retourne (événements clos, détections de la trame)."""
        p = self.params
        dets = detect_emissions(frame, self._det_params())
        if p.channels_only:
            dets = [d for d in dets if self._channel_for(d) is not None]
        now = frame.timestamp
        seen: set[int] = set()
        for d in dets:
            # association à la piste la plus proche en fréquence
            best, best_df = None, None
            # (plusieurs détections peuvent alimenter la même piste : lobes d'une FM)
            for i, t in enumerate(self._tracks):
                df = abs(t.freq - d.center_freq_hz)
                if df <= p.freq_tolerance_hz and (best_df is None or df < best_df):
                    best, best_df = i, df
            above_open = d.excess_db >= p.open_threshold_db
            if best is None:
                if not above_open:
                    continue  # le seuil de maintien ne crée pas de nouvelle piste
                self._tracks.append(
                    _Track(
                        start_ts=now,
                        last_ts=now,
                        freqs=[d.center_freq_hz],
                        peak_db=d.channel_power_dbfs,
                        pow_lin=[float(from_db(d.channel_power_dbfs))],
                        snrs=[d.snr_db],
                        bws=[d.bandwidth_hz] if d.bandwidth_hz else [],
                        consecutive_open=1,
                        active=p.persistence_frames <= 1,
                        channel=self._channel_for(d),
                        tuned_freq_hz=frame.center_freq_hz,
                        frames=1,
                    )
                )
                seen.add(len(self._tracks) - 1)
                continue
            t = self._tracks[best]
            seen.add(best)
            t.last_ts = now
            t.frames += 1
            t.freqs.append(d.center_freq_hz)
            t.peak_db = max(t.peak_db, d.channel_power_dbfs)
            t.pow_lin.append(float(from_db(d.channel_power_dbfs)))
            t.snrs.append(d.snr_db)
            if d.bandwidth_hz:
                t.bws.append(d.bandwidth_hz)
            if t.channel is None:
                t.channel = self._channel_for(d)
            if not t.active:
                t.consecutive_open = t.consecutive_open + 1 if above_open else 0
                if t.consecutive_open == 0:
                    # retombé sous le seuil d'ouverture avant confirmation
                    t.start_ts = now
                if t.consecutive_open >= p.persistence_frames:
                    t.active = True

        closed: list[ActivityEvent] = []
        keep: list[_Track] = []
        for i, t in enumerate(self._tracks):
            if i in seen:
                keep.append(t)
                continue
            if not t.active:
                self.false_alarm_rejected += 1
                continue
            if now - t.last_ts <= p.hang_time_s:
                keep.append(t)
                continue
            ev = self._close(t)
            if ev is not None:
                closed.append(ev)
        self._tracks = keep
        return closed, dets

    def flush(self) -> list[ActivityEvent]:
        """Clôt toutes les pistes actives (arrêt de l'acquisition)."""
        out = [ev for t in self._tracks if t.active and (ev := self._close(t)) is not None]
        self._tracks.clear()
        return out

    def _close(self, t: _Track) -> ActivityEvent | None:
        duration = t.last_ts - t.start_ts
        if duration < self.params.min_duration_s:
            self.false_alarm_rejected += 1
            return None
        return ActivityEvent(
            receiver_id=self.receiver_id,
            tuned_freq_hz=t.tuned_freq_hz,
            emission_freq_hz=float(np.mean(t.freqs)),
            start_ts=t.start_ts,
            end_ts=t.last_ts,
            peak_power_dbfs=float(t.peak_db),
            mean_power_dbfs=float(to_db(np.mean(t.pow_lin))),
            snr_db=float(np.median(t.snrs)),
            bandwidth_hz=float(np.median(t.bws)) if t.bws else None,
            freq_std_hz=float(np.std(t.freqs)),
            detection_params=self.params.to_dict(),
            simulated=self.simulated,
            channel_name=t.channel.name if t.channel else None,
            channel_freq_hz=t.channel.center_hz if t.channel else None,
            frames=t.frames,
        )
