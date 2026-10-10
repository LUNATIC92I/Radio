"""Console technique : journal de l'application et commandes de diagnostic (sans exécution de code arbitraire)."""

from __future__ import annotations

import logging
import shlex

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPlainTextEdit

from ...drivers.registry import backend_status, discover_devices
from ...models import ReceiverConfig
from ...reports.builder import fmt_freq, fmt_ts
from ...selftest import run_selftests
from ..widgets import Page, button

HELP = """Commandes disponibles :
  help                       cette aide
  status                     état de l'acquisition et du récepteur
  devices                    lister les récepteurs détectés
  backends                   pilotes disponibles
  start | stop               démarrer / arrêter l'acquisition
  tune <MHz>                 fréquence centrale
  rate <kS/s>                fréquence d'échantillonnage
  gain <dB|auto>             gain du récepteur
  detections                 émissions de la trame courante
  events [n]                 n derniers événements (défaut 10)
  selftest                   autotests de la chaîne de mesure
  audit [n]                  n dernières entrées du journal d'audit
  clear                      effacer la console"""


class ConsolePage(Page):
    title = "Console technique"
    subtitle = "Journal de fonctionnement et commandes de diagnostic. Seules les commandes listées sont acceptées."

    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.level = QComboBox()
        for name, lvl in (("INFO", logging.INFO), ("AVERTISSEMENT", logging.WARNING), ("ERREUR", logging.ERROR)):
            self.level.addItem(name, lvl)
        bar.addWidget(self.level)
        bar.addStretch(1)
        bar.addWidget(button("Effacer", lambda: self.out.clear()))
        self.root.addLayout(bar)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumBlockCount(5000)
        mono = QFont("DejaVu Sans Mono")
        mono.setStyleHint(QFont.Monospace)
        self.out.setFont(mono)
        self.root.addWidget(self.out, 1)
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("Commande (tapez « help »)")
        self.cmd.setFont(mono)
        self.cmd.returnPressed.connect(self._run)
        self.root.addWidget(self.cmd)
        ctx.log_line.connect(self._log)
        ctx.status.connect(lambda m: self.write(f"[état] {m}"))
        self.write("LUNATIC RADIO LAB — console technique. Tapez « help ».")

    def write(self, line: str) -> None:
        self.out.appendPlainText(line)
        self.out.moveCursor(QTextCursor.End)

    def _log(self, line: str, level: int) -> None:
        if level >= self.level.currentData():
            self.write(line)

    def _run(self) -> None:
        text = self.cmd.text().strip()
        self.cmd.clear()
        if not text:
            return
        self.write(f"> {text}")
        try:
            for line in self.execute(text):
                self.write(line)
        except Exception as exc:  # noqa: BLE001
            self.write(f"Erreur : {exc}")

    def execute(self, text: str) -> list[str]:
        parts = shlex.split(text)
        cmd, args = parts[0].lower(), parts[1:]
        ctx = self.ctx
        ctx.db.audit(ctx.access.actor, "console.command", {"command": text[:200]})
        if cmd == "help":
            return HELP.splitlines()
        if cmd == "clear":
            self.out.clear()
            return []
        if cmd == "status":
            cfg = ctx.receiver.config
            fr = ctx.last_frame
            out = [f"Récepteur : {ctx.device.label} ({ctx.device.status_text})",
                   f"Acquisition : {'en cours' if ctx.running else 'arrêtée'} — "
                   f"{'SIMULATION' if ctx.simulated else 'réel'}",
                   f"Config : {fmt_freq(cfg.center_freq_hz)}, {cfg.sample_rate_hz / 1e3:g} kS/s, gain "
                   f"{'auto' if cfg.gain_db is None else cfg.gain_db}"]
            if fr is not None:
                out.append(f"Dernière trame : plancher {fr.noise_floor_dbfs:.1f} dBFS, RBW {fr.rbw_hz:.0f} Hz, "
                           f"saturation {fr.saturation_ratio:.3%}")
            if ctx.engine:
                out.append(f"Trames : {ctx.engine.frames}, événements : {ctx.engine.events_total}, "
                           f"erreurs : {len(ctx.engine.errors)}")
            return out
        if cmd == "devices":
            return [f"- {d.label} [{d.backend}] {d.frequency_summary()} — {d.status_text}"
                    for d in discover_devices(allow_network=bool(ctx.db.get_setting("allow_network_devices", False)))]
        if cmd == "backends":
            return [f"{k} : {'disponible' if v else 'absent'}" for k, v in backend_status().items()]
        if cmd == "start":
            return ["Acquisition démarrée." if ctx.start_acquisition() else "Échec du démarrage."]
        if cmd == "stop":
            ctx.stop_acquisition()
            return ["Acquisition arrêtée."]
        if cmd in ("tune", "rate", "gain"):
            if not args:
                return [f"Usage : {cmd} <valeur>"]
            c = ctx.receiver.config
            cfg = ReceiverConfig(c.center_freq_hz, c.sample_rate_hz, c.gain_db, c.bandwidth_hz, c.ppm_correction,
                                 c.antenna)
            if cmd == "tune":
                cfg.center_freq_hz = float(args[0].replace(",", ".")) * 1e6
            elif cmd == "rate":
                cfg.sample_rate_hz = float(args[0].replace(",", ".")) * 1e3
            else:
                cfg.gain_db = None if args[0].lower() == "auto" else float(args[0].replace(",", "."))
            ctx.apply_config(cfg)
            return [f"Appliqué : {fmt_freq(cfg.center_freq_hz)}, {cfg.sample_rate_hz / 1e3:g} kS/s, gain "
                    f"{'auto' if cfg.gain_db is None else cfg.gain_db}"]
        if cmd == "detections":
            return [f"{fmt_freq(d.center_freq_hz)}  {d.channel_power_dbfs:7.1f} dBFS  SNR {d.snr_db:5.1f} dB  "
                    f"BW {'n/m' if d.bandwidth_hz is None else f'{d.bandwidth_hz:.0f} Hz'}"
                    for d in ctx.last_detections] or ["Aucune émission dans la trame courante."]
        if cmd == "events":
            n = int(args[0]) if args else 10
            return [f"#{e.id} {fmt_ts(e.start_ts)} {e.duration_s:6.2f} s {fmt_freq(e.emission_freq_hz)} "
                    f"{e.mean_power_dbfs:6.1f} dBFS {'SIMULÉ' if e.simulated else 'RÉEL'} {e.classification or ''}"
                    for e in ctx.db.query_events(limit=n)] or ["Aucun événement."]
        if cmd == "selftest":
            res = run_selftests()
            for r in res:
                ctx.db.add_test_result(r)
            return [f"[{'OK' if r.passed else 'ÉCHEC'}] {r.name}" for r in res]
        if cmd == "audit":
            n = int(args[0]) if args else 15
            return [f"{fmt_ts(a['ts'])} {a['actor']} {a['action']} {'ok' if a['success'] else 'REFUSÉ'} {a['details']}"
                    for a in ctx.db.list_audit(n)]
        return [f"Commande inconnue : {cmd} (tapez « help »)."]
