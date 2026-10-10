"""Gestion des équipements : détection, capacités, assistant de configuration et test de réception."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel, QListWidget, QProgressBar, QSplitter, QVBoxLayout,
    QWidget, QWizard, QWizardPage,
)

from ...drivers.registry import backend_status, create_receiver, discover_devices
from ...drivers.simulated import SimulatedReceiver
from ...models import DeviceInfo, ReceiverConfig
from ...selftest import reception_test
from ..widgets import Page, button, error_box, fill_table, guarded, make_table, mhz_spin
from .spectrum import SAMPLE_RATES


class _Worker(QObject):
    done = Signal(object)

    def __init__(self, fn):  # noqa: ANN001
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn())
        except Exception as exc:  # noqa: BLE001
            self.done.emit(exc)


def run_in_thread(parent: QObject, fn, on_done) -> QThread:  # noqa: ANN001
    th = QThread(parent)
    w = _Worker(fn)
    w.moveToThread(th)
    th.started.connect(w.run)
    w.done.connect(on_done)
    w.done.connect(th.quit)
    th.finished.connect(w.deleteLater)
    th._worker = w  # type: ignore[attr-defined] — garde une référence
    th.start()
    return th


class DevicesPage(Page):
    title = "Gestion des équipements"
    subtitle = ("Récepteurs détectés, capacités déclarées par leur pilote et état de connexion. Sans matériel, "
                "le logiciel fonctionne en mode simulation (clairement signalé).")

    def __init__(self, ctx):
        super().__init__(ctx)
        self.net = QCheckBox("Inclure les récepteurs réseau")
        self.net.setToolTip("Désactivé par défaut : le logiciel fonctionne localement")
        self.net.toggled.connect(self._net_toggled)
        self.header_right_lay.addWidget(self.net)
        self.header_right_lay.addWidget(button("Rechercher", self.refresh))
        self.header_right_lay.addWidget(button("Assistant de configuration…", self.wizard, "primary"))
        self.backends = QLabel("—")
        self.backends.setObjectName("hint")
        self.root.addWidget(self.backends)
        split = QSplitter(Qt.Horizontal)
        self.table = make_table(["Équipement", "Fabricant", "Modèle", "Pilote", "Plage de fréquences", "État"])
        self.table.itemSelectionChanged.connect(self._details)
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        g = QGroupBox("Capacités déclarées")
        self.form = QFormLayout(g)
        self.caps: dict[str, QLabel] = {}
        for k in ("Identifiant", "Fabricant", "Modèle", "N° de série", "Interface", "Fréquences", "Échantillonnage",
                  "Gain", "Antennes", "ADC", "Voies RX", "Émission matérielle", "État"):
            lbl = QLabel("—")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.caps[k] = lbl
            self.form.addRow(k, lbl)
        rl.addWidget(g)
        self.notes = QListWidget()
        self.notes.setWordWrap(True)
        rl.addWidget(QLabel("Remarques"))
        rl.addWidget(self.notes, 1)
        rl.addWidget(button("Utiliser cet équipement", self.use_selected, "primary"))
        split.addWidget(right)
        split.setSizes([750, 450])
        self.root.addWidget(split, 1)
        self.devices: list[DeviceInfo] = []
        self.refresh()

    def _net_toggled(self, on: bool) -> None:
        if not on:
            self.ctx.db.set_setting("allow_network_devices", False)
            self.refresh()
            return

        def _do() -> bool:
            self.ctx.access.require("network.devices", {"enabled": True})
            self.ctx.db.set_setting("allow_network_devices", True)
            return True

        if guarded(self.ctx, self, _do) is None:
            self.net.blockSignals(True)
            self.net.setChecked(False)
            self.net.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        st = backend_status()
        self.backends.setText("Pilotes : " + " · ".join(f"{k} {'✔' if v else '✘ (non installé)'}" for k, v in st.items())
                              + " — voir docs/GUIDE_SDR.md pour l'installation.")
        self.devices = discover_devices(include_simulation=True,
                                        allow_network=bool(self.ctx.db.get_setting("allow_network_devices", False)))
        fill_table(self.table, [(d.label, d.manufacturer, d.model, d.backend, d.frequency_summary(), d.status_text)
                                for d in self.devices], data=self.devices)
        self.ctx.db.audit(self.ctx.access.actor, "devices.scan", {"count": len(self.devices)})
        if self.devices:
            self.table.selectRow(0)

    def _selected(self) -> DeviceInfo | None:
        items = self.table.selectedItems()
        return self.table.item(items[0].row(), 0).data(Qt.UserRole) if items else None

    def _details(self) -> None:
        d = self._selected()
        if d is None:
            return
        rates = (f"{min(d.sample_rates_hz) / 1e3:g} – {max(d.sample_rates_hz) / 1e3:g} kS/s"
                 if d.sample_rates_hz else "non déclaré")
        vals = {
            "Identifiant": d.device_id, "Fabricant": d.manufacturer, "Modèle": d.model, "N° de série": d.serial or "—",
            "Interface": d.backend, "Fréquences": d.frequency_summary(), "Échantillonnage": rates,
            "Gain": f"{d.gain_range_db[0]:.1f} – {d.gain_range_db[1]:.1f} dB" if d.gain_range_db[1] > d.gain_range_db[0]
            else "non déclaré", "Antennes": ", ".join(d.antennas) or "—",
            "ADC": f"{d.adc_bits} bits" if d.adc_bits else "non déclaré", "Voies RX": str(d.rx_channels),
            "Émission matérielle": "déclarée — DÉSACTIVÉE (réception seule)" if d.tx_declared else "non",
            "État": d.status_text,
        }
        for k, v in vals.items():
            self.caps[k].setText(v)
        self.notes.clear()
        self.notes.addItems(d.notes or ["—"])

    def use_selected(self) -> None:
        d = self._selected()
        if d is None:
            return
        try:
            self.ctx.select_device(d)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Équipement indisponible", exc)

    def wizard(self) -> None:
        w = SetupWizard(self.ctx, self.devices, self)
        w.exec()


class SetupWizard(QWizard):
    """Sélection → compatibilité → test de réception → application."""

    def __init__(self, ctx, devices: list[DeviceInfo], parent=None):  # noqa: ANN001
        super().__init__(parent)
        self.ctx = ctx
        self.devices = devices
        self.setWindowTitle("Assistant de configuration du récepteur")
        self.setMinimumSize(720, 520)
        self.result_cfg: ReceiverConfig | None = None
        self.test_passed = False

        p1 = QWizardPage()
        p1.setTitle("1. Sélection de l'équipement")
        l1 = QFormLayout(p1)
        self.dev_combo = QComboBox()
        for d in devices:
            self.dev_combo.addItem(f"{d.label} — {d.status_text}", d)
        self.freq = mhz_spin(ctx.receiver.config.center_freq_hz)
        self.rate = QComboBox()
        for r in SAMPLE_RATES:
            self.rate.addItem(f"{r / 1e3:g} kS/s", r)
        self.rate.setCurrentIndex(max(0, self.rate.findData(int(ctx.receiver.config.sample_rate_hz))))
        l1.addRow("Équipement", self.dev_combo)
        l1.addRow("Fréquence centrale prévue", self.freq)
        l1.addRow("Échantillonnage", self.rate)
        self.addPage(p1)

        p2 = _CompatPage(self)
        self.addPage(p2)

        p3 = _TestPage(self)
        self.addPage(p3)

        p4 = QWizardPage()
        p4.setTitle("4. Application")
        l4 = QVBoxLayout(p4)
        self.final = QLabel()
        self.final.setWordWrap(True)
        l4.addWidget(self.final)
        self.addPage(p4)
        self.currentIdChanged.connect(self._page_changed)

    def device(self) -> DeviceInfo:
        return self.dev_combo.currentData()

    def cfg(self) -> ReceiverConfig:
        return ReceiverConfig(self.freq.value() * 1e6, float(self.rate.currentData()), 30.0)

    def _page_changed(self, i: int) -> None:
        if i == 3:
            d = self.device()
            self.final.setText(
                f"Équipement : {d.label}\nFréquence : {self.freq.value():.6f} MHz\n"
                f"Test de réception : {'RÉUSSI' if self.test_passed else 'non réussi / non exécuté'}\n\n"
                "Cliquez sur « Terminer » pour utiliser cet équipement avec ces paramètres.")

    def accept(self) -> None:
        try:
            self.ctx.select_device(self.device())
            self.ctx.apply_config(self.cfg())
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Application impossible", exc)
            return
        super().accept()


class _CompatPage(QWizardPage):
    def __init__(self, wiz: SetupWizard):
        super().__init__()
        self.wiz = wiz
        self.setTitle("2. Vérification de compatibilité")
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        lay.addWidget(self.list)

    def initializePage(self) -> None:  # noqa: N802
        w = self.wiz
        d = w.device()
        cfg = w.cfg()
        self.list.clear()
        items: list[str] = []
        if d.backend == "usb":
            items.append("⛔ Matériel branché mais pilote SDR absent : installez SoapySDR et son module (GUIDE_SDR).")
        if d.simulated:
            items.append("ℹ Mode simulation : aucune réception réelle, les données seront marquées SIMULÉES.")
        if d.tx_declared:
            items.append("ℹ Le matériel sait émettre : le logiciel ne l'utilise qu'en réception.")
        if d.freq_ranges_hz:
            ok = d.supports_frequency(cfg.center_freq_hz)
            items.append(("✔" if ok else "⛔") + f" Fréquence {cfg.center_freq_hz / 1e6:.4f} MHz "
                         + ("dans" if ok else "hors de") + f" la plage déclarée ({d.frequency_summary()}).")
        else:
            items.append("⚠ Plage de fréquences non déclarée par le pilote.")
        if d.sample_rates_hz:
            lo, hi = min(d.sample_rates_hz), max(d.sample_rates_hz)
            ok = lo <= cfg.sample_rate_hz <= hi
            items.append(("✔" if ok else "⛔") + f" Échantillonnage {cfg.sample_rate_hz / 1e3:g} kS/s "
                         f"(plage {lo / 1e3:g}–{hi / 1e3:g} kS/s).")
        chans = w.ctx.channels.list()
        if chans:
            inside = [c for c in chans if d.supports_frequency(c.low_hz) and d.supports_frequency(c.high_hz)]
            items.append(f"{'✔' if len(inside) == len(chans) else '⚠'} {len(inside)}/{len(chans)} canaux autorisés "
                         "dans les capacités de ce récepteur.")
            visible = [c for c in chans if abs(c.center_freq_hz - cfg.center_freq_hz) < cfg.sample_rate_hz / 2]
            items.append(f"ℹ {len(visible)} canal(aux) autorisé(s) visibles dans la bande observée.")
        else:
            items.append("⚠ Aucun canal autorisé défini (écran « Canaux autorisés »).")
        items.append("ℹ Les protocoles numériques ne sont caractérisés que par leurs propriétés physiques ; "
                     "aucun décodage n'est effectué.")
        self.list.addItems(items)


class _TestPage(QWizardPage):
    def __init__(self, wiz: SetupWizard):
        super().__init__()
        self.wiz = wiz
        self.setTitle("3. Test de réception")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Lecture d'une seconde d'échantillons : débit effectif, plancher de bruit, saturation, "
                             "composante continue."))
        self.btn = button("Lancer le test", self.run, "primary")
        lay.addWidget(self.btn)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        lay.addWidget(self.bar)
        self.res = make_table(["Mesure", "Valeur"])
        lay.addWidget(self.res, 1)
        self._th = None

    def run(self) -> None:
        w = self.wiz
        d = w.device()
        if w.ctx.running:
            w.ctx.stop_acquisition()
        try:
            rx = SimulatedReceiver(w.ctx.scenario, realtime=False) if d.simulated else create_receiver(d)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Test impossible", exc)
            return
        self.bar.setRange(0, 0)
        self.btn.setEnabled(False)
        cfg = w.cfg()
        self._th = run_in_thread(self, lambda: reception_test(rx, cfg, 1.0), self._done)

    def _done(self, res) -> None:  # noqa: ANN001
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.btn.setEnabled(True)
        if isinstance(res, Exception):
            error_box(self, "Test de réception", res)
            return
        self.wiz.ctx.db.add_test_result(res)
        self.wiz.test_passed = res.passed
        rows = [("Résultat", "RÉUSSI" if res.passed else "ÉCHEC"), ("Nature", "SIMULATION" if res.simulated else "RÉEL")]
        for k, v in res.details.items():
            if isinstance(v, dict):
                continue
            rows.append((k, f"{v:.4g}" if isinstance(v, float) else str(v)))
        fill_table(self.res, rows)
