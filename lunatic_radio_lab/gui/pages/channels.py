"""Gestion des canaux de test autorisés (administrateur)."""

from __future__ import annotations

import csv
import io
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget,
)

from ...channels import AuthorizedChannel, validate_channel
from ...protocols.profiles import all_profiles
from ...reports.builder import fmt_freq
from ...security.files import ImportRejected, secure_import
from ..widgets import Page, button, error_box, fill_table, guarded, make_table, mhz_spin, spin


class ChannelsPage(Page):
    title = "Canaux autorisés"
    subtitle = ("Canaux de test que vous êtes autorisé à surveiller. Le logiciel reste en réception seule : "
                "un canal ne permet jamais d'émettre. Aucune liste de fréquences sensibles n'est fournie.")

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header_right_lay.addWidget(button("Importer le plan PMR446 (UE)", self.import_pmr))
        self.header_right_lay.addWidget(button("Importer…", self.import_file))
        self.header_right_lay.addWidget(button("Exporter…", self.export_file))
        split = QSplitter(Qt.Horizontal)
        self.table = make_table(["Nom", "Fréquence", "Largeur", "Usage", "Équipement", "Profil", "Juridiction",
                                 "Autorisation", "Enregistrement"])
        self.table.itemSelectionChanged.connect(self._load_selected)
        split.addWidget(self.table)
        form_w = QWidget()
        fl = QVBoxLayout(form_w)
        fl.setContentsMargins(0, 0, 0, 0)
        g = QGroupBox("Canal")
        f = QFormLayout(g)
        self.name = QLineEdit()
        self.freq = mhz_spin(446.00625e6)
        self.bw = spin(12.5, 0.1, 10_000, "kHz", 3, 0.5)
        self.usage = QLineEdit()
        self.equipment = QLineEdit()
        self.profile = QComboBox()
        self.profile.addItem("— aucun —", None)
        for p in all_profiles():
            self.profile.addItem(p.name, p.id)
        self.jur = QLineEdit()
        self.auth = QLineEdit()
        self.auth.setPlaceholderText("n° de licence, convention, ordre de mission…")
        self.rec = QCheckBox("Enregistrement / démodulation audio autorisés")
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(60)
        f.addRow("Nom", self.name)
        f.addRow("Fréquence centrale", self.freq)
        f.addRow("Largeur de bande", self.bw)
        f.addRow("Usage", self.usage)
        f.addRow("Équipements associés", self.equipment)
        f.addRow("Profil attendu", self.profile)
        f.addRow("Juridiction", self.jur)
        f.addRow("Référence d'autorisation", self.auth)
        f.addRow("", self.rec)
        f.addRow("Notes", self.notes)
        row = QHBoxLayout()
        row.addWidget(button("Nouveau", self.clear_form))
        row.addWidget(button("Vérifier", self.check))
        row.addWidget(button("Enregistrer", self.save, "primary"))
        row.addWidget(button("Supprimer", self.delete, "danger"))
        f.addRow(row)
        fl.addWidget(g)
        fl.addWidget(QLabel("Validation"))
        self.msgs = QListWidget()
        self.msgs.setWordWrap(True)
        fl.addWidget(self.msgs, 1)
        split.addWidget(form_w)
        split.setSizes([800, 420])
        self.root.addWidget(split, 1)
        self.current_id: int | None = None
        self.refresh()
        ctx.channels_changed.connect(self.refresh)

    def refresh(self) -> None:
        chans = self.ctx.channels.list()
        fill_table(self.table, [(c.name, fmt_freq(c.center_freq_hz), f"{c.bandwidth_hz / 1e3:g} kHz", c.usage,
                                 c.equipment, c.profile_id or "—", c.jurisdiction, c.authorization_ref or "⚠ absente",
                                 "oui" if c.recording_allowed else "non") for c in chans], data=chans)

    def _form(self) -> AuthorizedChannel:
        return AuthorizedChannel(
            name=self.name.text().strip(), center_freq_hz=self.freq.value() * 1e6, bandwidth_hz=self.bw.value() * 1e3,
            usage=self.usage.text(), equipment=self.equipment.text(), profile_id=self.profile.currentData(),
            jurisdiction=self.jur.text(), authorization_ref=self.auth.text().strip(),
            recording_allowed=self.rec.isChecked(), notes=self.notes.toPlainText(), id=self.current_id,
        )

    def _load_selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        c: AuthorizedChannel = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        self.current_id = c.id
        self.name.setText(c.name)
        self.freq.setValue(c.center_freq_hz / 1e6)
        self.bw.setValue(c.bandwidth_hz / 1e3)
        self.usage.setText(c.usage)
        self.equipment.setText(c.equipment)
        self.profile.setCurrentIndex(max(0, self.profile.findData(c.profile_id)))
        self.jur.setText(c.jurisdiction)
        self.auth.setText(c.authorization_ref)
        self.rec.setChecked(c.recording_allowed)
        self.notes.setPlainText(c.notes)
        self.check()

    def clear_form(self) -> None:
        self.current_id = None
        for w in (self.name, self.usage, self.equipment, self.jur, self.auth):
            w.clear()
        self.notes.clear()
        self.rec.setChecked(False)
        self.msgs.clear()

    def check(self) -> None:
        rep = validate_channel(self._form(), self.ctx.channels.list(), self.ctx.device,
                               self.ctx.receiver.config.sample_rate_hz)
        self._show(rep)

    def _show(self, rep) -> None:  # noqa: ANN001
        self.msgs.clear()
        self.msgs.addItems([f"⛔ {e}" for e in rep.errors] + [f"⚠ {w}" for w in rep.warnings])
        if rep.ok and not rep.warnings:
            self.msgs.addItem("✔ Paramètres valides.")

    def save(self) -> None:
        ch = self._form()
        rep = guarded(self.ctx, self, lambda: self.ctx.channels.save(ch, self.ctx.device))
        if rep is None:
            return
        self._show(rep)
        if rep.ok:
            self.current_id = ch.id
            self.ctx.refresh_channel_windows()
            self.ctx.notify.emit(f"Canal « {ch.name} » enregistré.", "ok")
        else:
            self.ctx.notify.emit("Canal non enregistré : corrigez les erreurs.", "error")

    def delete(self) -> None:
        if self.current_id is None:
            return
        if QMessageBox.question(self, "Supprimer", f"Supprimer le canal « {self.name.text()} » ?") != QMessageBox.Yes:
            return
        cid = self.current_id
        if guarded(self.ctx, self, lambda: self.ctx.channels.delete(cid) or True):
            self.clear_form()
            self.ctx.refresh_channel_windows()

    def import_pmr(self) -> None:
        n = guarded(self.ctx, self, self.ctx.channels.import_pmr446)
        if n is not None:
            self.ctx.refresh_channel_windows()
            self.ctx.notify.emit(f"{n} canal(aux) PMR446 importé(s). Vérifiez la réglementation nationale.", "ok")

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer des canaux", "", "Canaux (*.json *.csv)")
        if not path:
            return
        try:
            imp = secure_import(path, "json" if path.lower().endswith(".json") else "csv")
            text = imp.path.read_text(encoding="utf-8-sig")
            if path.lower().endswith(".json"):
                records = json.loads(text)
                if not isinstance(records, list):
                    raise ImportRejected("Le JSON doit contenir une liste de canaux.")
            else:
                records = list(csv.DictReader(io.StringIO(text)))
        except (ImportRejected, Exception) as exc:  # noqa: BLE001
            error_box(self, "Import refusé", exc)
            return
        res = guarded(self.ctx, self, lambda: self.ctx.channels.import_records(records))
        if res is None:
            return
        ok, problems = res
        self.ctx.refresh_channel_windows()
        msg = f"{ok} canal(aux) importé(s)."
        if problems:
            msg += "\n\nProblèmes :\n" + "\n".join(problems[:20])
        QMessageBox.information(self, "Import des canaux", msg)

    def export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exporter les canaux", "canaux_autorises.json",
                                              "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        data = self.ctx.channels.export_csv() if path.lower().endswith(".csv") else self.ctx.channels.export_json()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data)
        self.ctx.db.audit(self.ctx.access.actor, "channels.export", {"path": path})
        self.ctx.notify.emit("Canaux exportés.", "ok")
