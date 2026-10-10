"""Mode laboratoire : génération de signaux synthétiques, sans aucune émission radio."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QSplitter,
    QVBoxLayout, QWidget,
)

from ...drivers.simulated import SimulatedReceiver, simulated_device_info
from ...dsp.synth import EMITTER_KINDS, Emitter, Scenario, preset_scenarios
from ...security.files import ImportRejected, secure_import
from ..widgets import Page, badge, button, error_box, fill_table, make_table, mhz_spin, spin

KIND_DEFAULTS = {
    "carrier": {"deviation_hz": 0.0},
    "fm_tone": {"deviation_hz": 2_500.0, "tone_hz": 1_000.0},
    "fm_voice": {"deviation_hz": 2_500.0},
    "fsk4_tdma": {"deviation_hz": 1_944.0, "symbol_rate": 4_800.0},
    "fsk4_cont": {"deviation_hz": 1_800.0, "symbol_rate": 4_800.0},
    "fsk4_narrow": {"deviation_hz": 1_050.0, "symbol_rate": 2_400.0},
    "noise_burst": {"bandwidth_hz": 10_000.0},
}


class LabPage(Page):
    title = "Mode laboratoire"
    subtitle = ("Signaux synthétiques générés localement pour tester la chaîne d'analyse. Aucune émission radio "
                "réelle. Toutes les données issues de ce mode sont marquées SIMULÉES.")

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header_right_lay.addWidget(badge("DONNÉES SIMULÉES", "simBadge"))
        bar = QHBoxLayout()
        self.preset = QComboBox()
        for key, sc in preset_scenarios().items():
            self.preset.addItem(sc.name, key)
        bar.addWidget(QLabel("Scénario prédéfini"))
        bar.addWidget(self.preset)
        bar.addWidget(button("Charger", self.load_preset))
        bar.addStretch(1)
        bar.addWidget(button("Ouvrir JSON…", self.open_json))
        bar.addWidget(button("Enregistrer JSON…", self.save_json))
        bar.addWidget(button("Appliquer au récepteur simulé", self.apply, "primary"))
        self.root.addLayout(bar)
        self.desc = QLabel("")
        self.desc.setObjectName("hint")
        self.desc.setWordWrap(True)
        self.root.addWidget(self.desc)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        g0 = QGroupBox("Scénario")
        f0 = QFormLayout(g0)
        self.name = QLineEdit()
        self.noise = spin(-60, -120, 0, "dBFS (bruit total)", 1, 1)
        self.noise.setToolTip("Niveau de bruit : plusieurs niveaux permettent d'évaluer les seuils de détection")
        self.seed = spin(1234, 0, 1e9, "", 0, 1)
        f0.addRow("Nom", self.name)
        f0.addRow("Bruit", self.noise)
        f0.addRow("Graine aléatoire", self.seed)
        ll.addWidget(g0)
        self.table = make_table(["Actif", "Type", "Fréquence", "Puissance", "Excursion", "Rythme", "Libellé"])
        self.table.itemSelectionChanged.connect(self._load_emitter)
        ll.addWidget(self.table, 1)
        split.addWidget(left)
        g = QGroupBox("Émetteur simulé")
        f = QFormLayout(g)
        self.kind = QComboBox()
        for k, v in EMITTER_KINDS.items():
            self.kind.addItem(v, k)
        self.kind.currentIndexChanged.connect(self._kind_defaults)
        self.freq = mhz_spin(446.00625e6)
        self.power = spin(-40, -120, 0, "dBFS", 1, 1)
        self.dev = spin(2500, 0, 20_000, "Hz", 0, 50)
        self.tone = spin(1000, 10, 5_000, "Hz", 0, 10)
        self.ctcss = spin(0, 0, 260, "Hz (0 = aucun)", 1, 0.1)
        self.sym = spin(4800, 100, 20_000, "Bd", 0, 100)
        self.bw = spin(10, 0.5, 200, "kHz", 1, 0.5)
        self.intermittent = QCheckBox("Émission intermittente")
        self.on = spin(2, 0.05, 60, "s actif", 2, 0.1)
        self.off = spin(3, 0, 60, "s inactif", 2, 0.1)
        self.phase = spin(0, 0, 60, "s décalage", 2, 0.1)
        self.fade = spin(0, 0, 40, "dB", 1, 1)
        self.fade_rate = spin(0.2, 0.01, 10, "Hz", 2, 0.05)
        self.drift = spin(0, -500, 500, "Hz/s", 1, 1)
        self.label = QLineEdit()
        self.enabled = QCheckBox("Actif")
        self.enabled.setChecked(True)
        for lab, w in (("Type", self.kind), ("Fréquence", self.freq), ("Puissance", self.power),
                       ("Excursion", self.dev), ("Tonalité", self.tone), ("CTCSS", self.ctcss),
                       ("Débit symbole", self.sym), ("Largeur (bruit)", self.bw), ("", self.intermittent),
                       ("Durée active", self.on), ("Durée inactive", self.off), ("Décalage", self.phase),
                       ("Variation de puissance", self.fade), ("Rythme de variation", self.fade_rate),
                       ("Dérive de fréquence", self.drift), ("Libellé", self.label), ("", self.enabled)):
            f.addRow(lab, w)
        row = QHBoxLayout()
        row.addWidget(button("Ajouter", self.add))
        row.addWidget(button("Mettre à jour", self.update_sel))
        row.addWidget(button("Supprimer", self.remove, "danger"))
        f.addRow(row)
        split.addWidget(g)
        split.setSizes([700, 420])
        self.root.addWidget(split, 1)
        self.scenario = ctx.scenario
        self._show_scenario()

    # ------------------------------------------------------------------ modèle
    def _show_scenario(self) -> None:
        sc = self.scenario
        self.name.setText(sc.name)
        self.noise.setValue(sc.noise_dbfs)
        self.seed.setValue(sc.seed)
        self.desc.setText(sc.description)
        fill_table(self.table, [("oui" if e.enabled else "non", EMITTER_KINDS.get(e.kind, e.kind),
                                 f"{e.freq_hz / 1e6:.5f} MHz", f"{e.power_dbfs:.1f} dBFS",
                                 f"{e.deviation_hz:.0f} Hz",
                                 "permanent" if e.on_s is None else f"{e.on_s:g} s / {e.off_s:g} s", e.label)
                                for e in sc.emitters], data=list(range(len(sc.emitters))))

    def _kind_defaults(self) -> None:
        for k, v in KIND_DEFAULTS.get(self.kind.currentData(), {}).items():
            {"deviation_hz": self.dev, "tone_hz": self.tone, "symbol_rate": self.sym,
             "bandwidth_hz": self.bw}[k].setValue(v / 1e3 if k == "bandwidth_hz" else v)

    def _form(self) -> Emitter:
        return Emitter(
            kind=self.kind.currentData(), freq_hz=self.freq.value() * 1e6, power_dbfs=self.power.value(),
            deviation_hz=self.dev.value(), tone_hz=self.tone.value(), ctcss_hz=self.ctcss.value() or None,
            symbol_rate=self.sym.value(), bandwidth_hz=self.bw.value() * 1e3,
            on_s=self.on.value() if self.intermittent.isChecked() else None, off_s=self.off.value(),
            phase_s=self.phase.value(), fading_depth_db=self.fade.value(), fading_rate_hz=self.fade_rate.value(),
            drift_hz_per_s=self.drift.value(), label=self.label.text(), enabled=self.enabled.isChecked(),
        )

    def _sel(self) -> int | None:
        items = self.table.selectedItems()
        return self.table.item(items[0].row(), 0).data(Qt.UserRole) if items else None

    def _load_emitter(self) -> None:
        i = self._sel()
        if i is None:
            return
        e = self.scenario.emitters[i]
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(max(0, self.kind.findData(e.kind)))
        self.kind.blockSignals(False)
        self.freq.setValue(e.freq_hz / 1e6)
        self.power.setValue(e.power_dbfs)
        self.dev.setValue(e.deviation_hz)
        self.tone.setValue(e.tone_hz)
        self.ctcss.setValue(e.ctcss_hz or 0)
        self.sym.setValue(e.symbol_rate)
        self.bw.setValue(e.bandwidth_hz / 1e3)
        self.intermittent.setChecked(e.on_s is not None)
        self.on.setValue(e.on_s or 2.0)
        self.off.setValue(e.off_s)
        self.phase.setValue(e.phase_s)
        self.fade.setValue(e.fading_depth_db)
        self.fade_rate.setValue(e.fading_rate_hz)
        self.drift.setValue(e.drift_hz_per_s)
        self.label.setText(e.label)
        self.enabled.setChecked(e.enabled)

    def _sync_header(self) -> None:
        self.scenario.name = self.name.text() or "Scénario"
        self.scenario.noise_dbfs = self.noise.value()
        self.scenario.seed = int(self.seed.value())

    def add(self) -> None:
        self.scenario.emitters.append(self._form())
        self._show_scenario()

    def update_sel(self) -> None:
        i = self._sel()
        if i is not None:
            self.scenario.emitters[i] = self._form()
            self._show_scenario()

    def remove(self) -> None:
        i = self._sel()
        if i is not None:
            del self.scenario.emitters[i]
            self._show_scenario()

    def load_preset(self) -> None:
        self.scenario = preset_scenarios()[self.preset.currentData()]
        self._show_scenario()

    def apply(self) -> None:
        self._sync_header()
        sc = Scenario.from_dict(self.scenario.to_dict())
        if not isinstance(self.ctx.receiver, SimulatedReceiver):
            self.ctx.select_device(simulated_device_info())
        self.ctx.set_scenario(sc)
        self.ctx.notify.emit(f"Scénario « {sc.name} » appliqué au récepteur simulé.", "ok")

    def save_json(self) -> None:
        self._sync_header()
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le scénario", f"{self.scenario.name}.json",
                                              "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.scenario.to_dict(), fh, indent=2, ensure_ascii=False)

    def open_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un scénario", "", "JSON (*.json)")
        if not path:
            return
        try:
            imp = secure_import(path, "json")
            d = json.loads(imp.path.read_text(encoding="utf-8"))
            sc = Scenario.from_dict(d)
            for e in sc.emitters:
                if e.kind not in EMITTER_KINDS:
                    raise ImportRejected(f"Type d'émetteur inconnu : {e.kind}")
        except (ImportRejected, Exception) as exc:  # noqa: BLE001
            error_box(self, "Scénario invalide", exc)
            return
        self.scenario = sc
        self._show_scenario()
