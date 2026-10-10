"""Sécurité et conformité : accès administrateur, journal d'audit, juridiction, rappels légaux."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QTextBrowser, QVBoxLayout

from ...reports.builder import fmt_ts
from ...security.access import SENSITIVE_ACTIONS
from ..widgets import Page, button, fill_table, guarded, make_table, set_pin_dialog, unlock_dialog

LEGAL_SUMMARY = """
<h3>Principes intégrés au logiciel</h3>
<ul>
<li><b>Réception seule</b> : aucune fonction d'émission, de brouillage ou d'usurpation de station.</li>
<li><b>Aucun déchiffrement</b> : les protocoles numériques sont seulement caractérisés par leurs propriétés physiques.</li>
<li><b>Fonctionnement local</b> : aucune donnée n'est envoyée sur le réseau ; les récepteurs réseau sont désactivés par défaut.</li>
<li><b>Enregistrement encadré</b> : démodulation et capture IQ réelles limitées aux canaux autorisés à l'enregistrement,
avec attestation de l'opérateur et journalisation.</li>
</ul>
<h3>Rappels réglementaires (non exhaustifs — voir docs/CONFORMITE_LEGALE.md)</h3>
<ul>
<li>La réception d'une émission n'autorise ni son enregistrement, ni sa divulgation, ni son exploitation.
En France, l'interception de correspondances émises par voie électronique est sanctionnée (art. 226-15 du Code pénal),
et le secret des correspondances s'impose à tous.</li>
<li>Les bandes, puissances et usages sont fixés par chaque pays (ANFR / ARCEP en France, autorités nationales ailleurs).
PMR446 : usage sans licence dans l'UE (décision ECC/DEC/(15)05), à vérifier localement ; non autorisé aux États-Unis.</li>
<li>Les communications professionnelles (DMR, P25…) ne doivent être surveillées que dans le cadre d'une autorisation
explicite (propriétaire du réseau, mission de maintenance, laboratoire agréé).</li>
<li>Ces informations ne constituent pas un avis juridique : consultez l'autorité compétente.</li>
</ul>
"""


class SecurityPage(Page):
    title = "Sécurité et conformité"
    subtitle = "Contrôle d'accès aux paramètres sensibles, journal des actions et exigences légales."

    def __init__(self, ctx):
        super().__init__(ctx)
        top = QHBoxLayout()
        g = QGroupBox("Accès administrateur")
        f = QFormLayout(g)
        self.state = QLabel("—")
        f.addRow("État", self.state)
        row = QHBoxLayout()
        row.addWidget(button("Déverrouiller", self.unlock, "primary"))
        row.addWidget(button("Verrouiller", self.lock))
        row.addWidget(button("Définir / changer le code", lambda: set_pin_dialog(ctx, self)))
        f.addRow(row)
        f.addRow(QLabel("Actions protégées : " + " · ".join(SENSITIVE_ACTIONS.values())))
        self.jur = QLineEdit(ctx.db.get_setting("jurisdiction", ""))
        self.jur.setPlaceholderText("ex. France (ANFR/ARCEP), Belgique (IBPT), Tchad (ARCEP Tchad)…")
        f.addRow("Juridiction d'utilisation", self.jur)
        f.addRow(button("Enregistrer la juridiction", self.save_jur))
        top.addWidget(g, 1)
        legal = QTextBrowser()
        legal.setHtml(LEGAL_SUMMARY)
        legal.setOpenExternalLinks(False)
        top.addWidget(legal, 1)
        self.root.addLayout(top, 2)
        ga = QGroupBox("Journal d'audit (actions horodatées)")
        la = QVBoxLayout(ga)
        self.audit = make_table(["Date", "Acteur", "Action", "Résultat", "Détails"])
        la.addWidget(self.audit)
        la.addWidget(button("Rafraîchir", self.refresh))
        self.root.addWidget(ga, 3)
        ctx.access_changed.connect(lambda _: self.refresh())
        self.refresh()

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        a = self.ctx.access
        if not a.has_pin:
            self.state.setText("⚠ Aucun code défini — les actions sensibles exigeront d'en créer un.")
        elif a.unlocked:
            self.state.setText(f"🔓 Déverrouillé ({int(a.remaining_s // 60)} min restantes)")
        else:
            self.state.setText("🔒 Verrouillé")
        fill_table(self.audit, [(fmt_ts(r["ts"]), r["actor"], r["action"], "ok" if r["success"] else "REFUSÉ",
                                 str(r["details"])[:200]) for r in self.ctx.db.list_audit(500)])

    def unlock(self) -> None:
        unlock_dialog(self.ctx, self)
        self.refresh()

    def lock(self) -> None:
        self.ctx.access.lock()
        self.ctx.access_changed.emit(False)
        self.refresh()

    def save_jur(self) -> None:
        val = self.jur.text().strip()

        def _do() -> bool:
            self.ctx.access.require("jurisdiction.edit", {"value": val})
            self.ctx.db.set_setting("jurisdiction", val)
            return True

        if guarded(self.ctx, self, _do):
            self.ctx.notify.emit("Juridiction enregistrée.", "ok")
            self.refresh()

