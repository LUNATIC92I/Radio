"""Analyse audio de laboratoire (enregistrements légaux, transmissions de test autorisées)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QVBoxLayout,
    QWidget,
)

from ... import paths
from ...dsp import audio as A
from ...dsp.demod import channelize, fm_demodulate
from ...iq_io import read_sigmf
from ...security.files import ImportRejected, secure_import, secure_import_sigmf
from .. import theme
from ..widgets import Page, button, error_box, fill_table, make_table, mhz_spin, spin

try:  # QtMultimedia peut être absent (bibliothèques système manquantes)
    from PySide6.QtMultimedia import QAudioFormat, QAudioOutput, QAudioSink, QMediaDevices, QMediaPlayer

    HAVE_MM = True
except Exception:  # noqa: BLE001
    HAVE_MM = False

ATTESTATION = ("Je confirme que cette transmission relève d'un essai de laboratoire ou d'une communication pour "
               "laquelle je dispose des autorisations de réception et d'enregistrement nécessaires.")


class AudioPage(Page):
    title = "Analyse audio de laboratoire"
    subtitle = ("Fichiers enregistrés légalement ou transmissions de test autorisées. Aucun décodage de voix "
                "numérique, aucun contournement de chiffrement.")

    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        bar.addWidget(button("Ouvrir un fichier audio…", self.open_file, "primary"))
        bar.addWidget(button("Démoduler FM (capture en direct)", self.demod_live,
                             tooltip="Canaux autorisés à l'enregistrement uniquement"))
        bar.addWidget(button("Démoduler FM (fichier SigMF)…", self.demod_file))
        bar.addWidget(button("Clip de test synthétique", self.synthetic))
        bar.addStretch(1)
        self.play_btn = button("▶ Lecture", self.play)
        self.play_btn.setEnabled(HAVE_MM)
        if not HAVE_MM:
            self.play_btn.setToolTip("QtMultimedia indisponible sur ce système")
        bar.addWidget(self.play_btn)
        bar.addWidget(button("■ Stop", self.stop))
        bar.addWidget(button("Exporter WAV…", self.export))
        self.root.addLayout(bar)
        self.src = QLabel("Aucun clip chargé.")
        self.src.setObjectName("hint")
        self.root.addWidget(self.src)
        mid = QHBoxLayout()
        plots = QWidget()
        pl = QVBoxLayout(plots)
        pl.setContentsMargins(0, 0, 0, 0)
        self.wave = pg.PlotWidget()
        self.wave.setLabel("bottom", "Temps", units="s")
        self.wave.setLabel("left", "Amplitude (pleine échelle = 1)")
        self.wave.showGrid(x=True, y=True, alpha=0.2)
        self.wave_hi = self.wave.plot(pen=pg.mkPen(theme.ELECTRIC))
        self.wave_lo = self.wave.plot(pen=pg.mkPen(theme.ELECTRIC))
        self.fill = pg.FillBetweenItem(self.wave_hi, self.wave_lo, brush=pg.mkBrush(30, 144, 255, 90))
        self.wave.addItem(self.fill)
        self.region = pg.LinearRegionItem((0, 0.5), brush=pg.mkBrush(0, 209, 255, 40))
        self.wave.addItem(self.region)
        pl.addWidget(self.wave, 1)
        self.spec = pg.PlotWidget()
        self.spec.setLabel("bottom", "Temps", units="s")
        self.spec.setLabel("left", "Fréquence", units="Hz")
        self.spec_img = pg.ImageItem()
        self.spec.addItem(self.spec_img)
        self.spec_bar = pg.ColorBarItem(values=(-100, -20), colorMap=theme.waterfall_colormap(), label="dBFS", width=10)
        self.spec_bar.setImageItem(self.spec_img, insert_in=self.spec.getPlotItem())
        pl.addWidget(self.spec, 1)
        mid.addWidget(plots, 3)
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        g = QGroupBox("Mesure du niveau sonore")
        gl = QVBoxLayout(g)
        self.levels = make_table(["Grandeur", "Valeur"])
        gl.addWidget(self.levels)
        sl.addWidget(g, 2)
        g2 = QGroupBox("Traitements (enregistrements de test)")
        f = QFormLayout(g2)
        self.lo = spin(300, 20, 8000, "Hz", 0, 50)
        self.hi = spin(3400, 100, 20000, "Hz", 0, 100)
        f.addRow("Passe-bande bas", self.lo)
        f.addRow("Passe-bande haut", self.hi)
        f.addRow(button("Appliquer le passe-bande", self.do_bandpass))
        self.red = spin(12, 1, 40, "dB", 0, 1)
        f.addRow("Réduction de bruit", self.red)
        f.addRow(button("Réduire le bruit", self.do_denoise))
        self.target = spin(-1.0, -40, 0, "dBFS", 1, 0.5)
        f.addRow("Cible normalisation crête", self.target)
        f.addRow(button("Normaliser", self.do_normalize))
        r = QHBoxLayout()
        r.addWidget(button("Découper (sélection)", self.do_trim))
        r.addWidget(button("Couper les silences", self.do_autotrim))
        f.addRow(r)
        f.addRow(button("↶ Annuler le dernier traitement", self.undo))
        sl.addWidget(g2, 3)
        g3 = QGroupBox("Écoute en direct (canaux autorisés)")
        f3 = QFormLayout(g3)
        self.mon_freq = mhz_spin(446.00625e6)
        self.mon_sq = spin(8, 0, 40, "dB", 0, 1)
        self.mon_rec = QCheckBox("Enregistrer en WAV (canal avec enregistrement autorisé)")
        self.mon_level = QProgressBar()
        self.mon_level.setRange(0, 100)
        self.mon_level.setFormat("niveau %p %")
        self.mon_state = QLabel("Écoute arrêtée")
        self.mon_state.setObjectName("hint")
        self.mon_state.setWordWrap(True)
        f3.addRow("Fréquence", self.mon_freq)
        f3.addRow("", button("Prendre l'émission la plus forte", self._mon_pick))
        f3.addRow("Squelch", self.mon_sq)
        f3.addRow("", self.mon_rec)
        r3 = QHBoxLayout()
        self.mon_btn = button("▶ Écouter", self.toggle_monitor, "primary")
        r3.addWidget(self.mon_btn)
        f3.addRow(r3)
        f3.addRow(self.mon_level)
        f3.addRow(self.mon_state)
        sl.addWidget(g3, 2)
        mid.addWidget(side, 1)
        self.root.addLayout(mid, 1)
        self.clip: A.AudioClip | None = None
        self.history: list[A.AudioClip] = []
        self._tmp = Path(tempfile.mkdtemp(prefix="lrl_audio_"))
        self.sink = None
        self.sink_dev = None
        ctx.audio_chunk.connect(self._on_audio)
        ctx.monitor_changed.connect(self._mon_changed)
        self.player = None
        if HAVE_MM:
            try:
                self.player = QMediaPlayer(self)
                self._out = QAudioOutput(self)
                self.player.setAudioOutput(self._out)
            except Exception:  # noqa: BLE001
                self.player = None
                self.play_btn.setEnabled(False)

    # ------------------------------------------------------------------ sources
    def set_clip(self, clip: A.AudioClip, label: str, push: bool = False) -> None:
        if push and self.clip is not None:
            self.history.append(self.clip)
            self.history = self.history[-10:]
        self.clip = clip
        nature = "DONNÉES SIMULÉES" if clip.simulated else "enregistrement"
        self.src.setText(f"{label} — {clip.duration_s:.2f} s à {clip.sample_rate} Hz ({nature})")
        self._redraw()

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Fichier audio", "",
                                              "Audio (*.wav *.mp3 *.flac *.ogg *.opus *.m4a)")
        if not path:
            return
        try:
            imp = secure_import(path, "audio")
            clip = A.load_audio(imp.path)
        except (ImportRejected, Exception) as exc:  # noqa: BLE001
            error_box(self, "Import refusé", exc)
            return
        self.ctx.db.audit(self.ctx.access.actor, "file.import",
                          {"kind": "audio", "name": imp.original_name, "sha256": imp.sha256, "size": imp.size})
        self.history.clear()
        self.set_clip(clip, f"Fichier : {imp.original_name} (SHA-256 {imp.sha256[:12]}…)")

    def synthetic(self) -> None:
        self.history.clear()
        self.set_clip(A.synthetic_test_clip(), "Clip de test synthétique (tonalité 1 kHz hachée + bruit)")

    def _attest(self) -> bool:
        r = QMessageBox.question(self, "Autorisation requise", ATTESTATION, QMessageBox.Yes | QMessageBox.No,
                                 QMessageBox.No)
        return r == QMessageBox.Yes

    def demod_live(self) -> None:
        eng = self.ctx.engine
        if eng is None or eng.last_frame is None:
            error_box(self, "Démodulation", "Aucune acquisition en cours.")
            return
        dets = self.ctx.last_detections
        if not dets:
            error_box(self, "Démodulation", "Aucune émission détectée dans la trame courante.")
            return
        d = max(dets, key=lambda x: x.channel_power_dbfs)
        snap = eng.snapshot(4.0)
        bw = 12_500.0
        if not snap.simulated:
            ch = self.ctx.channels.recording_permitted(d.center_freq_hz - bw / 2, d.center_freq_hz + bw / 2)
            if ch is None:
                self.ctx.db.audit(self.ctx.access.actor, "audio.demod", {"freq_hz": d.center_freq_hz,
                                                                         "result": "refusé : canal non autorisé"}, False)
                error_box(self, "Démodulation refusée",
                          f"{d.center_freq_hz / 1e6:.5f} MHz n'appartient à aucun canal autorisé à l'enregistrement. "
                          "Un administrateur doit enregistrer ce canal avec une référence d'autorisation.")
                return
            if not self._attest():
                return
        self._demod(snap.iq, snap.sample_rate, d.center_freq_hz - snap.center_freq, snap.simulated,
                    f"Démodulation FM en direct à {d.center_freq_hz / 1e6:.5f} MHz")

    def demod_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Capture SigMF", "", "SigMF (*.sigmf-meta)")
        if not path:
            return
        try:
            imp = secure_import_sigmf(path)
            cap = read_sigmf(imp.path)
        except (ImportRejected, Exception) as exc:  # noqa: BLE001
            error_box(self, "Import refusé", exc)
            return
        if not cap.simulated and not self._attest():
            return
        iq = cap.read(0, min(cap.num_samples, int(30 * cap.sample_rate)))
        p = np.abs(np.fft.fftshift(np.fft.fft(iq[: 1 << 16] if len(iq) >= 1 << 16 else iq))) ** 2
        f = np.fft.fftshift(np.fft.fftfreq(len(p), 1 / cap.sample_rate))
        offset = float(f[int(np.argmax(p))])
        self._demod(iq, cap.sample_rate, offset, cap.simulated, f"Démodulation FM de {imp.original_name} "
                    f"({(cap.center_freq + offset) / 1e6:.5f} MHz)")

    def _demod(self, iq: np.ndarray, fs: float, offset: float, simulated: bool, label: str) -> None:
        try:
            x, fs2 = channelize(iq, fs, offset, 12_500.0, min_rate=32_000.0)
            audio = fm_demodulate(x, fs2, 16_000.0, deviation_hz=2_500.0)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Démodulation", exc)
            return
        self.ctx.db.audit(self.ctx.access.actor, "audio.demod", {"label": label, "simulated": simulated})
        self.history.clear()
        self.set_clip(A.AudioClip(audio, 16_000, label, simulated), label)

    # ------------------------------------------------------------------ écoute en direct
    def _mon_pick(self) -> None:
        dets = self.ctx.last_detections
        if dets:
            self.mon_freq.setValue(max(dets, key=lambda d: d.channel_power_dbfs).center_freq_hz / 1e6)

    def toggle_monitor(self) -> None:
        if self.ctx.engine is not None and self.ctx.engine.monitor is not None:
            path = self.ctx.stop_monitor()
            if path:
                self.ctx.notify.emit(f"Enregistrement écrit : {path}", "ok")
            return
        f = self.mon_freq.value() * 1e6
        rec = None
        if self.mon_rec.isChecked():
            tag = "SIMULE_" if self.ctx.simulated else ""
            rec = str(paths.captures_dir() / f"ecoute_{tag}{f / 1e6:.5f}MHz_{int(time.time())}.wav")
        attested = self.ctx.simulated or self._attest()
        if not attested:
            return
        try:
            reason = self.ctx.start_monitor(f, 12_500.0, self.mon_sq.value(), rec, attested=True)
        except (PermissionError, RuntimeError, ValueError) as exc:
            error_box(self, "Écoute refusée", exc)
            return
        self._open_sink()
        self.mon_state.setText(reason + ("" if self.sink_dev is not None else
                                        " — aucune sortie audio disponible : niveau affiché uniquement."))

    def _open_sink(self) -> None:
        self.sink = self.sink_dev = None
        if not HAVE_MM:
            return
        try:
            dev = QMediaDevices.defaultAudioOutput()
            if dev.isNull():
                return
            fmt = QAudioFormat()
            fmt.setSampleRate(16_000)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.Int16)
            self.sink = QAudioSink(dev, fmt, self)
            self.sink_dev = self.sink.start()
        except Exception:  # noqa: BLE001
            self.sink = self.sink_dev = None

    def _on_audio(self, audio, squelch_open: bool) -> None:  # noqa: ANN001
        rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
        self.mon_level.setValue(int(min(100, rms * 140)))
        if self.sink_dev is not None:
            try:
                self.sink_dev.write((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
            except Exception:  # noqa: BLE001
                self.sink_dev = None

    def _mon_changed(self, on: bool) -> None:
        self.mon_btn.setText("■ Arrêter l'écoute" if on else "▶ Écouter")
        if not on:
            if self.sink is not None:
                self.sink.stop()
            self.sink = self.sink_dev = None
            self.mon_level.setValue(0)
            self.mon_state.setText("Écoute arrêtée")

    # ------------------------------------------------------------------ traitements
    def _apply(self, fn, name: str) -> None:  # noqa: ANN001
        if self.clip is None:
            return
        try:
            new = fn(self.clip)
        except Exception as exc:  # noqa: BLE001
            error_box(self, name, exc)
            return
        self.set_clip(new, self.src.text().split(" — ")[0] + f" + {name}", push=True)

    def do_bandpass(self) -> None:
        self._apply(lambda c: A.bandpass(c, self.lo.value(), self.hi.value()), "passe-bande")

    def do_denoise(self) -> None:
        self._apply(lambda c: A.reduce_noise(c, self.red.value()), "réduction de bruit")

    def do_normalize(self) -> None:
        self._apply(lambda c: A.normalize(c, self.target.value()), "normalisation")

    def do_trim(self) -> None:
        a, b = self.region.getRegion()
        self._apply(lambda c: A.trim(c, max(0.0, a), b), "découpage")

    def do_autotrim(self) -> None:
        self._apply(A.auto_trim_silence, "suppression des silences")

    def undo(self) -> None:
        if self.history:
            self.clip = self.history.pop()
            self._redraw()

    # ------------------------------------------------------------------ affichage / sortie
    def _redraw(self) -> None:
        c = self.clip
        if c is None:
            return
        t, lo, hi = A.waveform_envelope(c)
        self.wave_hi.setData(t, hi)
        self.wave_lo.setData(t, lo)
        self.region.setRegion((0, c.duration_s))
        self.region.setBounds((0, c.duration_s))
        f, tt, S = A.spectrogram(c)
        self.spec_img.setImage(S, autoLevels=False)
        if len(tt) > 1 and len(f) > 1:
            self.spec_img.setRect(0, 0, c.duration_s, f[-1])
        top = float(np.percentile(S, 99.5))
        self.spec_bar.setLevels((top - 70, top))
        fill_table(self.levels, A.measure_levels(c).as_rows() + [("Durée", f"{c.duration_s:.2f} s"),
                                                               ("Fréquence d'échantillonnage", f"{c.sample_rate} Hz")])

    def play(self) -> None:
        if self.clip is None or self.player is None:
            return
        p = self._tmp / f"play_{id(self.clip)}.wav"
        A.save_wav(self.clip, p)
        self.player.setSource(QUrl.fromLocalFile(str(p)))
        self.player.play()

    def stop(self) -> None:
        if self.player is not None:
            self.player.stop()

    def export(self) -> None:
        if self.clip is None:
            return
        default = str(paths.captures_dir() / ("clip_simule.wav" if self.clip.simulated else "clip.wav"))
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en WAV", default, "WAV (*.wav)")
        if not path:
            return
        A.save_wav(self.clip, path)
        self.ctx.db.audit(self.ctx.access.actor, "audio.export", {"path": path, "simulated": self.clip.simulated})
        self.ctx.notify.emit(f"Audio exporté : {path}", "ok")
