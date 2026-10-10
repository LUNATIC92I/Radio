"""Identification technique des signaux : caractéristiques observées et hypothèses avec confiance."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from ...dsp.classifier import DECISION_THRESHOLD, Classification, classify_iq
from ...iq_io import read_sigmf
from ...protocols.profiles import all_profiles
from ...security.files import ImportRejected, secure_import_sigmf
from ..widgets import Page, button, error_box, fill_table, make_table, mhz_spin, spin

FEATURE_LABELS = {
    "duration_s": ("Durée analysée", "s", 2), "snr_db": ("Rapport signal/bruit", "dB", 1),
    "obw_hz": ("Largeur de bande occupée 99 %", "Hz", 0), "envelope_cv": ("Coefficient de variation d'enveloppe", "", 3),
    "amplitude_variation_db": ("Variation d'amplitude (10 ms)", "dB", 1), "duty_cycle": ("Rapport cyclique", "", 2),
    "burst_count": ("Nombre de rafales", "", 0), "burst_mean_ms": ("Durée médiane des rafales", "ms", 1),
    "burst_period_ms": ("Période des rafales", "ms", 1), "freq_offset_hz": ("Décalage de fréquence", "Hz", 0),
    "freq_drift_hz_s": ("Dérive de fréquence", "Hz/s", 1), "freq_stability_hz": ("Stabilité (écart-type 50 ms)", "Hz", 1),
    "deviation_rms_hz": ("Excursion efficace", "Hz", 0), "deviation_peak_hz": ("Excursion crête (99e c.)", "Hz", 0),
    "symbol_rate_hz": ("Raie de débit symbole", "Hz", 1), "symbol_rate_strength_db": ("Intensité de la raie", "dB", 1),
    "fsk_levels": ("Niveaux de fréquence", "", 0), "ctcss_hz": ("CTCSS", "Hz", 1),
    "tone_hz": ("Tonalité audio dominante", "Hz", 0), "tone_purity": ("Pureté de la tonalité", "", 2),
    "voice_band_ratio": ("Énergie dans 300–3400 Hz", "", 2),
}


class IdentificationPage(Page):
    title = "Identification technique des signaux"
    subtitle = ("Caractérisation à partir de propriétés observables. Toute hypothèse est accompagnée d'un niveau "
                "de confiance et des observations qui la justifient. Aucun décodage de contenu n'est effectué.")

    def __init__(self, ctx):
        super().__init__(ctx)
        top = QHBoxLayout()
        g = QGroupBox("Source à analyser")
        f = QFormLayout(g)
        self.source = QComboBox()
        self.source.addItem("Capture en direct (tampon des dernières secondes)", "live")
        self.source.addItem("Fichier IQ SigMF", "file")
        self.freq = mhz_spin(446.00625e6)
        self.bw = spin(12.5, 1, 200, "kHz", 2, 0.5)
        self.dur = spin(2.0, 0.2, 4.0, "s", 1, 0.5)
        self.det_pick = QComboBox()
        self.det_pick.currentIndexChanged.connect(self._pick)
        f.addRow("Source", self.source)
        f.addRow("Émission détectée", self.det_pick)
        f.addRow("Fréquence à analyser", self.freq)
        f.addRow("Largeur d'analyse", self.bw)
        f.addRow("Durée (direct)", self.dur)
        row = QHBoxLayout()
        row.addWidget(button("Rafraîchir les détections", self._refresh_dets))
        row.addWidget(button("Analyser", self.analyze, "primary"))
        f.addRow(row)
        top.addWidget(g, 1)
        gv = QGroupBox("Résultat")
        lv = QVBoxLayout(gv)
        self.verdict = QLabel("—")
        self.verdict.setStyleSheet("font-size: 14pt; font-weight: 700; color: #E6E9EE")
        self.verdict.setWordWrap(True)
        self.nature = QLabel("")
        self.nature.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        lv.addWidget(self.verdict)
        lv.addWidget(self.nature)
        note = QLabel(f"Seuil de décision : {DECISION_THRESHOLD:.0%}. En dessous, le signal est « non identifié ». "
                      "Les profils numériques sont plafonnés car aucune trame n'est vérifiée.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lv.addWidget(note)
        top.addWidget(gv, 2)
        self.root.addLayout(top)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Hypothèses (classées par confiance)"))
        self.hyp = make_table(["Profil", "Confiance", "Éléments favorables", "Éléments contraires", "Non mesuré"])
        self.hyp.itemSelectionChanged.connect(self._hyp_detail)
        ll.addWidget(self.hyp, 2)
        self.detail = QListWidget()
        ll.addWidget(QLabel("Justification de l'hypothèse sélectionnée"))
        ll.addWidget(self.detail, 2)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Observations"))
        self.obs = QListWidget()
        self.obs.setWordWrap(True)
        rl.addWidget(self.obs, 2)
        rl.addWidget(QLabel("Caractéristiques mesurées"))
        self.feat = make_table(["Grandeur", "Valeur"])
        rl.addWidget(self.feat, 3)
        split.addWidget(right)
        split.setSizes([700, 500])
        self.root.addWidget(split, 1)
        pf = QLabel("Profils documentés : " + " · ".join(p.name for p in all_profiles()))
        pf.setObjectName("hint")
        pf.setWordWrap(True)
        self.root.addWidget(pf)
        self.result: Classification | None = None

    def on_show(self) -> None:
        self._refresh_dets()

    def _refresh_dets(self) -> None:
        self.det_pick.blockSignals(True)
        self.det_pick.clear()
        self.det_pick.addItem("— saisie manuelle —", None)
        for d in self.ctx.last_detections:
            self.det_pick.addItem(f"{d.center_freq_hz / 1e6:.5f} MHz · {d.channel_power_dbfs:.1f} dBFS · "
                                  f"SNR {d.snr_db:.0f} dB", d)
        self.det_pick.blockSignals(False)
        if len(self.ctx.last_detections) == 1:
            self.det_pick.setCurrentIndex(1)
            self._pick(1)

    def _pick(self, i: int) -> None:
        d = self.det_pick.itemData(i)
        if d is None:
            return
        self.freq.setValue(d.center_freq_hz / 1e6)
        if d.bandwidth_hz:
            self.bw.setValue(max(12.5, 1.5 * d.bandwidth_hz / 1e3))

    def analyze(self) -> None:
        try:
            if self.source.currentData() == "live":
                if self.ctx.engine is None:
                    raise RuntimeError("Aucune acquisition en cours : démarrez le récepteur ou choisissez un fichier.")
                snap = self.ctx.engine.snapshot(self.dur.value())
                if snap is None:
                    raise RuntimeError("Tampon IQ vide.")
                iq, fs, fc, sim = snap.iq, snap.sample_rate, snap.center_freq, snap.simulated
            else:
                path, _ = QFileDialog.getOpenFileName(self, "Capture SigMF", "", "SigMF (*.sigmf-meta)")
                if not path:
                    return
                imp = secure_import_sigmf(path)
                cap = read_sigmf(imp.path)
                n = min(cap.num_samples, int(4 * cap.sample_rate))
                iq, fs, fc, sim = cap.read(0, n), cap.sample_rate, cap.center_freq, cap.simulated
                self.ctx.db.audit(self.ctx.access.actor, "file.import", {"sha256": imp.sha256, "name": imp.original_name})
            offset = self.freq.value() * 1e6 - fc
            if abs(offset) > fs / 2:
                raise ValueError(f"La fréquence demandée est hors de la bande capturée "
                                 f"({(fc - fs / 2) / 1e6:.4f}–{(fc + fs / 2) / 1e6:.4f} MHz).")
            bw = min(self.bw.value() * 1e3, 0.8 * fs)
            self.result = classify_iq(iq, fs, offset, fc, bw, simulated=sim)
        except (ImportRejected, Exception) as exc:  # noqa: BLE001
            error_box(self, "Analyse impossible", exc)
            return
        self._show(self.result)
        self.ctx.db.audit(self.ctx.access.actor, "signal.classify",
                          {"freq_hz": self.freq.value() * 1e6, "verdict": self.result.verdict, "simulated": sim})

    def _show(self, c: Classification) -> None:
        self.verdict.setText(c.verdict)
        self.nature.setText("DONNÉES SIMULÉES" if c.simulated else "Mesure réelle")
        self.nature.setObjectName("simBadge" if c.simulated else "realBadge")
        self.nature.style().unpolish(self.nature)
        self.nature.style().polish(self.nature)
        fill_table(self.hyp, [(h.name, f"{h.confidence:.0%}", len(h.supporting), len(h.contradicting),
                               len(h.not_measured)) for h in c.hypotheses], data=c.hypotheses)
        self.obs.clear()
        self.obs.addItems(c.observations)
        rows = []
        for k, (lab, unit, nd) in FEATURE_LABELS.items():
            v = getattr(c.features, k)
            rows.append((lab, "non mesuré" if v is None else (f"{v:.{nd}f} {unit}".strip() if isinstance(v, float) else f"{v} {unit}".strip())))
        fill_table(self.feat, rows)
        if c.hypotheses:
            self.hyp.selectRow(0)

    def _hyp_detail(self) -> None:
        items = self.hyp.selectedItems()
        self.detail.clear()
        if not items:
            return
        h = self.hyp.item(items[0].row(), 0).data(Qt.UserRole)
        if h is None:
            return
        self.detail.addItems([f"✔ {s}" for s in h.supporting] + [f"✘ {s}" for s in h.contradicting]
                             + [f"? non mesuré : {s}" for s in h.not_measured] + [f"ℹ {n}" for n in h.notes])
