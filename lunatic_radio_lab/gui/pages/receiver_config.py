"""Configuration des récepteurs : paramètres RF, étalonnage, captures IQ, rejeu."""

from __future__ import annotations

import time

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
)

from ... import paths
from ...drivers.iqfile import IQFileReceiver
from ...iq_io import open_raw, read_sigmf, write_sigmf
from ...models import ReceiverConfig
from ...security.files import ImportRejected, secure_import, secure_import_sigmf
from ..widgets import Page, button, error_box, guarded, mhz_spin, spin
from .spectrum import SAMPLE_RATES


class ReceiverConfigPage(Page):
    title = "Configuration des récepteurs"
    subtitle = ("Paramètres appliqués dans les limites déclarées par le matériel. Réception seule : aucune "
                "fonction d'émission n'est disponible, quel que soit l'équipement.")

    def __init__(self, ctx):
        super().__init__(ctx)
        row = QHBoxLayout()
        g = QGroupBox("Paramètres radio")
        f = QFormLayout(g)
        self.dev = QLabel("—")
        self.dev.setWordWrap(True)
        self.freq = mhz_spin()
        self.rate = QComboBox()
        for r in SAMPLE_RATES:
            self.rate.addItem(f"{r / 1e3:g} kS/s", r)
        self.gain = spin(30, 0, 70, "dB", 1, 1)
        self.agc = QCheckBox("Gain automatique (AGC)")
        self.bw = spin(0, 0, 60_000, "kHz (0 = auto)", 0, 100)
        self.ppm = spin(0, -200, 200, "ppm", 1, 0.5)
        self.ppm.setToolTip("Correction de l'erreur de l'oscillateur du récepteur")
        self.ant = QComboBox()
        f.addRow("Récepteur", self.dev)
        f.addRow("Fréquence centrale", self.freq)
        f.addRow("Échantillonnage", self.rate)
        f.addRow("Gain", self.gain)
        f.addRow("", self.agc)
        f.addRow("Filtre analogique", self.bw)
        f.addRow("Correction", self.ppm)
        f.addRow("Antenne", self.ant)
        f.addRow(button("Appliquer", self.apply, "primary"))
        row.addWidget(g, 1)
        col = QVBoxLayout()
        g2 = QGroupBox("Étalonnage de puissance (paramètre sensible)")
        f2 = QFormLayout(g2)
        self.cal_on = QCheckBox("Afficher en dBm à l'aide d'un décalage mesuré")
        self.cal = spin(0, -200, 200, "dB", 2, 0.1)
        f2.addRow(QLabel("Décalage = puissance connue (dBm) injectée par un générateur étalonné − puissance lue "
                         "(dBFS), au même gain. Valable uniquement pour ce gain, cette fréquence et ce câblage."))
        f2.addRow("", self.cal_on)
        f2.addRow("Décalage", self.cal)
        f2.addRow(button("Enregistrer l'étalonnage", self.save_cal))
        col.addWidget(g2)
        g3 = QGroupBox("Captures IQ (SigMF)")
        f3 = QFormLayout(g3)
        self.cap_dur = spin(2.0, 0.1, 4.0, "s", 1, 0.5)
        f3.addRow("Durée (tampon)", self.cap_dur)
        f3.addRow(button("Enregistrer une capture IQ", self.capture))
        f3.addRow(QLabel("Hors simulation, la capture n'est permise que si la bande observée est entièrement "
                         "couverte par des canaux autorisés à l'enregistrement."))
        self.raw_rate = spin(250, 1, 20_000, "kS/s", 1, 10)
        self.raw_fc = mhz_spin()
        self.raw_type = QComboBox()
        for t in ("cf32_le", "ci16_le", "cu8"):
            self.raw_type.addItem(t, t)
        f3.addRow(button("Rejouer un fichier SigMF…", self.replay_sigmf))
        f3.addRow("Brut : échantillonnage", self.raw_rate)
        f3.addRow("Brut : fréquence centrale", self.raw_fc)
        f3.addRow("Brut : format", self.raw_type)
        f3.addRow(button("Rejouer un fichier IQ brut…", self.replay_raw))
        col.addWidget(g3)
        g4 = QGroupBox("Opérateur")
        f4 = QFormLayout(g4)
        self.operator = QLineEdit(ctx.db.get_setting("operator_name", ""))
        f4.addRow("Nom (rapports)", self.operator)
        f4.addRow(button("Enregistrer", self._save_operator))
        col.addWidget(g4)
        col.addStretch(1)
        row.addLayout(col, 1)
        self.root.addLayout(row, 1)
        ctx.receiver_changed.connect(lambda _: self.load())
        self.load()

    def on_show(self) -> None:
        self.load()

    def load(self) -> None:
        d = self.ctx.device
        cfg = self.ctx.receiver.config
        self.dev.setText(f"{d.label} — {d.status_text}\nPlage : {d.frequency_summary()} · gain "
                         f"{d.gain_range_db[0]:.0f}–{d.gain_range_db[1]:.0f} dB"
                         + (" · ÉMISSION MATÉRIELLE DÉSACTIVÉE (réception seule)" if d.tx_declared else ""))
        self.freq.setValue(cfg.center_freq_hz / 1e6)
        i = self.rate.findData(int(cfg.sample_rate_hz))
        if i < 0:
            self.rate.addItem(f"{cfg.sample_rate_hz / 1e3:g} kS/s", int(cfg.sample_rate_hz))
            i = self.rate.count() - 1
        self.rate.setCurrentIndex(i)
        g0, g1 = d.gain_range_db
        if g1 > g0:
            self.gain.setRange(g0, g1)
        self.gain.setValue(cfg.gain_db if cfg.gain_db is not None else self.gain.value())
        self.agc.setChecked(cfg.gain_db is None)
        self.bw.setValue((cfg.bandwidth_hz or 0) / 1e3)
        self.ppm.setValue(cfg.ppm_correction)
        self.ant.clear()
        self.ant.addItem("— défaut —", None)
        for a in d.antennas:
            self.ant.addItem(a, a)
        self.ant.setCurrentIndex(max(0, self.ant.findData(cfg.antenna)))
        cal = self.ctx.calibration_offset_db
        self.cal_on.setChecked(cal is not None)
        self.cal.setValue(cal or 0.0)

    def apply(self) -> None:
        cfg = ReceiverConfig(self.freq.value() * 1e6, float(self.rate.currentData()),
                             None if self.agc.isChecked() else self.gain.value(),
                             self.bw.value() * 1e3 or None, self.ppm.value(), self.ant.currentData())
        try:
            self.ctx.apply_config(cfg)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Configuration refusée", exc)
            return
        self.ctx.notify.emit("Configuration du récepteur appliquée.", "ok")

    def save_cal(self) -> None:
        val = self.cal.value() if self.cal_on.isChecked() else None

        def _do() -> bool:
            self.ctx.access.require("calibration.edit", {"offset_db": val})
            self.ctx.db.set_setting("calibration_offset_db", val)
            return True

        if guarded(self.ctx, self, _do):
            self.ctx.notify.emit("Étalonnage enregistré." if val is not None else "Étalonnage désactivé (dBFS).", "ok")

    def _save_operator(self) -> None:
        self.ctx.db.set_setting("operator_name", self.operator.text().strip())
        self.ctx.notify.emit("Nom de l'opérateur enregistré.", "ok")

    def capture(self) -> None:
        eng = self.ctx.engine
        if eng is None or not eng.running:
            error_box(self, "Capture IQ", "Démarrez d'abord l'acquisition.")
            return
        snap = eng.snapshot(self.cap_dur.value())
        if snap is None:
            error_box(self, "Capture IQ", "Tampon vide.")
            return
        lo, hi = snap.center_freq - snap.sample_rate / 2, snap.center_freq + snap.sample_rate / 2
        if not snap.simulated:
            ch = self.ctx.channels.recording_permitted(lo, hi)
            if ch is None:
                self.ctx.db.audit(self.ctx.access.actor, "iq.capture", {"result": "refusé", "low": lo, "high": hi}, False)
                error_box(self, "Capture refusée",
                          "La bande observée n'est pas entièrement couverte par un canal autorisé à l'enregistrement. "
                          "Réduisez l'échantillonnage ou faites enregistrer un canal par l'administrateur.")
                return
        base = paths.captures_dir() / f"capture_{'SIMULEE_' if snap.simulated else ''}{time.strftime('%Y%m%d_%H%M%S')}"
        cap = write_sigmf(base, snap.iq, snap.sample_rate, snap.center_freq, snap.simulated,
                          description="Capture LUNATIC RADIO LAB" + (" (DONNÉES SIMULÉES)" if snap.simulated else ""),
                          hw=self.ctx.device.label)
        self.ctx.db.audit(self.ctx.access.actor, "iq.capture", {"path": str(cap.data_path), "simulated": snap.simulated})
        self.ctx.notify.emit(f"Capture enregistrée : {cap.data_path}", "ok")

    def replay_sigmf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Capture SigMF", str(paths.captures_dir()), "SigMF (*.sigmf-meta)")
        if not path:
            return
        try:
            imp = secure_import_sigmf(path)
            cap = read_sigmf(imp.path)
        except (ImportRejected, Exception) as exc:  # noqa: BLE001
            error_box(self, "Rejeu impossible", exc)
            return
        self.ctx.use_iq_file(IQFileReceiver(cap))
        self.ctx.notify.emit(f"Rejeu prêt : {imp.original_name} ({cap.duration_s:.1f} s). Démarrez l'acquisition.", "ok")

    def replay_raw(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Fichier IQ brut", "", "IQ (*.cfile *.cf32 *.cs16 *.cu8 *.bin *.raw)")
        if not path:
            return
        try:
            imp = secure_import(path, "iq")
            cap = open_raw(imp.path, self.raw_rate.value() * 1e3, self.raw_fc.value() * 1e6, self.raw_type.currentData())
        except (ImportRejected, Exception) as exc:  # noqa: BLE001
            error_box(self, "Rejeu impossible", exc)
            return
        self.ctx.use_iq_file(IQFileReceiver(cap))
        self.ctx.notify.emit("Rejeu brut prêt. Démarrez l'acquisition.", "ok")

