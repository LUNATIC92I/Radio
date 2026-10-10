"""Rapport PDF (ReportLab) : résumé, équipements, paramètres, plages, graphiques,
événements (réels et simulés séparés), tests, erreurs et limites techniques."""

from __future__ import annotations

import os
from pathlib import Path

import reportlab
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..models import ActivityEvent
from .builder import ReportData, fmt_freq, fmt_ts

GRAPHITE = colors.HexColor("#1B1E24")
SILVER = colors.HexColor("#AEB4BE")
ELECTRIC = colors.HexColor("#1E90FF")
WARN = colors.HexColor("#E0A100")
SIM_COLOR = colors.HexColor("#B04BD8")

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_SANITIZE = {"≈": "~", "≤": "<=", "≥": ">=", "≠": "!=", "→": "->", "✓": "OK", "✗": "X", "…": "...", "²": "2"}


def _register_fonts() -> None:
    global _FONT, _FONT_BOLD
    if _FONT != "Helvetica":
        return
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        (os.path.join(os.path.dirname(reportlab.__file__), "fonts", "Vera.ttf"),
         os.path.join(os.path.dirname(reportlab.__file__), "fonts", "VeraBd.ttf")),
    ]
    for reg, bold in candidates:
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("LRL", reg))
                pdfmetrics.registerFont(TTFont("LRL-Bold", bold))
                _FONT, _FONT_BOLD = "LRL", "LRL-Bold"
                return
            except Exception:  # noqa: BLE001
                continue


def _t(s: object) -> str:
    txt = str(s)
    for a, b in _SANITIZE.items():
        txt = txt.replace(a, b)
    return txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _d(s: object) -> str:
    """Texte pour les dessins (pas d'échappement HTML)."""
    txt = str(s)
    for a, b in _SANITIZE.items():
        txt = txt.replace(a, b)
    return txt


def _styles() -> dict[str, ParagraphStyle]:
    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["Normal"], fontName=_FONT, fontSize=9, leading=12)
    return {
        "body": base,
        "small": ParagraphStyle("s", parent=base, fontSize=7.5, leading=9.5),
        "title": ParagraphStyle("t", parent=base, fontName=_FONT_BOLD, fontSize=20, leading=24, textColor=GRAPHITE),
        "subtitle": ParagraphStyle("st", parent=base, fontSize=11, textColor=ELECTRIC),
        "h1": ParagraphStyle("h1", parent=base, fontName=_FONT_BOLD, fontSize=13, leading=16, spaceBefore=10,
                             spaceAfter=6, textColor=GRAPHITE),
        "h2": ParagraphStyle("h2", parent=base, fontName=_FONT_BOLD, fontSize=10.5, spaceBefore=6, spaceAfter=4,
                             textColor=ELECTRIC),
        "banner": ParagraphStyle("bn", parent=base, fontName=_FONT_BOLD, fontSize=10, textColor=colors.white,
                                 alignment=TA_CENTER),
        "cell": ParagraphStyle("c", parent=base, fontSize=7.2, leading=8.6),
    }


def _table(rows: list[list], col_widths: list[float] | None = None, header: bool = True, st=None) -> Table:
    st = st or _styles()
    hdr = ParagraphStyle("hdr", parent=st["cell"], textColor=colors.white, fontName=_FONT_BOLD)
    data = [[Paragraph(_t(c), hdr if (header and i == 0) else st["cell"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.3, SILVER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor("#F2F4F7")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), GRAPHITE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    t.setStyle(TableStyle(style))
    return t


def _banner(text: str, color, st) -> Table:
    t = Table([[Paragraph(_t(text), st["banner"])]], colWidths=[180 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def _spectrum_chart(data: ReportData) -> Drawing:
    sp = data.spectrum
    w, h = 175 * mm, 70 * mm
    d = Drawing(w, h)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 38, 28, w - 50, h - 45
    pts = [((f - sp.center_freq_hz) / 1e3, p) for f, p in zip(sp.freqs_hz, sp.power_dbfs)]
    floor = [(pts[0][0], sp.noise_floor_dbfs), (pts[-1][0], sp.noise_floor_dbfs)]
    lp.data = [pts, floor]
    lp.lines[0].strokeColor = SIM_COLOR if sp.simulated else ELECTRIC
    lp.lines[0].strokeWidth = 0.6
    lp.lines[1].strokeColor = WARN
    lp.lines[1].strokeDashArray = [3, 2]
    lp.lines[1].strokeWidth = 0.6
    ymin = min(p for _, p in pts)
    ymax = max(p for _, p in pts)
    lp.yValueAxis.valueMin = 10 * int(ymin // 10) - 10
    lp.yValueAxis.valueMax = 10 * int(ymax // 10) + 10
    lp.xValueAxis.labels.fontName = lp.yValueAxis.labels.fontName = _FONT
    lp.xValueAxis.labels.fontSize = lp.yValueAxis.labels.fontSize = 6.5
    d.add(lp)
    d.add(String(w / 2, 4, _d(f"Décalage / {sp.center_freq_hz / 1e6:.4f} MHz (kHz) — RBW {sp.rbw_hz:.0f} Hz"),
                 fontName=_FONT, fontSize=7, textAnchor="middle"))
    d.add(String(4, h / 2, "dBFS", fontName=_FONT, fontSize=7))
    d.add(String(w - 4, h - 10, _d("SIMULÉ" if sp.simulated else "MESURE RÉELLE"), fontName=_FONT_BOLD, fontSize=8,
                 textAnchor="end", fillColor=SIM_COLOR if sp.simulated else ELECTRIC))
    return d


def _timeline_chart(events: list[ActivityEvent], simulated: bool) -> Drawing:
    w, h = 175 * mm, 60 * mm
    d = Drawing(w, h)
    x0, y0, pw, ph = 50, 22, w - 62, h - 34
    d.add(Rect(x0, y0, pw, ph, strokeColor=SILVER, fillColor=None, strokeWidth=0.5))
    t0 = min(e.start_ts for e in events)
    t1 = max(e.end_ts for e in events)
    f0 = min(e.emission_freq_hz for e in events)
    f1 = max(e.emission_freq_hz for e in events)
    span_t = max(t1 - t0, 1e-3)
    span_f = max(f1 - f0, 1.0)
    col = SIM_COLOR if simulated else ELECTRIC
    for e in events:
        x = x0 + (e.start_ts - t0) / span_t * pw
        xw = max(1.0, e.duration_s / span_t * pw)
        y = y0 + 4 + (e.emission_freq_hz - f0) / span_f * (ph - 8)
        d.add(Rect(x, y - 1.5, xw, 3, fillColor=col, strokeColor=None))
    d.add(String(x0, 8, _d(f"Temps : {fmt_ts(t0)} → {fmt_ts(t1)} ({span_t:.1f} s)"), fontName=_FONT, fontSize=7))
    d.add(String(2, y0, f"{f0 / 1e6:.4f}", fontName=_FONT, fontSize=6.5))
    d.add(String(2, y0 + ph - 6, f"{f1 / 1e6:.4f}", fontName=_FONT, fontSize=6.5))
    d.add(String(2, y0 + ph / 2, "MHz", fontName=_FONT, fontSize=6.5))
    d.add(Line(x0, y0, x0 + pw, y0, strokeColor=SILVER))
    return d


def _power_histogram(events: list[ActivityEvent], simulated: bool) -> Drawing:
    w, h = 175 * mm, 55 * mm
    d = Drawing(w, h)
    p = [e.peak_power_dbfs for e in events]
    lo = 5 * int(min(p) // 5)
    hi = 5 * int(max(p) // 5) + 5
    edges = list(range(lo, hi + 1, 5))
    counts = [sum(1 for v in p if a <= v < a + 5) for a in edges[:-1]] or [len(p)]
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 38, 22, w - 50, h - 32
    bc.data = [counts]
    bc.categoryAxis.categoryNames = [f"{a}" for a in edges[:-1]] or [str(lo)]
    bc.bars[0].fillColor = SIM_COLOR if simulated else ELECTRIC
    bc.valueAxis.valueMin = 0
    bc.categoryAxis.labels.fontName = bc.valueAxis.labels.fontName = _FONT
    bc.categoryAxis.labels.fontSize = bc.valueAxis.labels.fontSize = 6.5
    d.add(bc)
    d.add(String(w / 2, 4, _d("Puissance crête des événements (dBFS, classes de 5 dB) — nombre d'événements"),
                 fontName=_FONT, fontSize=7, textAnchor="middle"))
    return d


def _events_table(events: list[ActivityEvent], st) -> Table:
    rows = [["#", "Début", "Durée (s)", "Fréq. émission", "Canal", "Crête dBFS", "Moy. dBFS", "SNR dB", "BW (Hz)",
             "Caractérisation (confiance)"]]
    for e in events[:400]:
        cls = "—"
        if e.classification:
            cls = f"{e.classification} ({e.classification_confidence:.0%})" if e.classification_confidence is not None \
                else e.classification
        rows.append([e.id or "", fmt_ts(e.start_ts), f"{e.duration_s:.2f}", fmt_freq(e.emission_freq_hz),
                     e.channel_name or "—", f"{e.peak_power_dbfs:.1f}", f"{e.mean_power_dbfs:.1f}", f"{e.snr_db:.1f}",
                     "n/m" if e.bandwidth_hz is None else f"{e.bandwidth_hz:.0f}", cls])
    return _table(rows, [8 * mm, 25 * mm, 13 * mm, 22 * mm, 18 * mm, 14 * mm, 14 * mm, 12 * mm, 13 * mm, 41 * mm], st=st)


def _event_section(story: list, title: str, events: list[ActivityEvent], simulated: bool, st) -> None:
    story.append(Paragraph(_t(title), st["h1"]))
    if simulated:
        story.append(_banner("DONNÉES SIMULÉES — générées par le mode laboratoire, aucune réception réelle",
                             SIM_COLOR, st))
        story.append(Spacer(1, 4))
    if not events:
        story.append(Paragraph("Aucun événement.", st["body"]))
        return
    story.append(Paragraph(_t("Chronologie (une barre par événement, position verticale = fréquence)"), st["h2"]))
    story.append(_timeline_chart(events, simulated))
    story.append(_power_histogram(events, simulated))
    story.append(Paragraph(_t(f"Liste des événements ({len(events)}"
                              + (", 400 premiers affichés" if len(events) > 400 else "") + ")"), st["h2"]))
    story.append(_events_table(events, st))


def write_pdf_report(data: ReportData, path: str | Path) -> Path:
    _register_fonts()
    st = _styles()
    path = Path(path)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=18 * mm,
                            bottomMargin=16 * mm, title=data.title, author=data.software)
    story: list = []
    story.append(Paragraph("LUNATIC RADIO LAB", st["subtitle"]))
    story.append(Paragraph(_t(data.title), st["title"]))
    story.append(Spacer(1, 6))
    if data.contains_simulated and data.contains_real:
        story.append(_banner("Ce rapport contient des MESURES RÉELLES et des DONNÉES SIMULÉES, présentées séparément.",
                             WARN, st))
    elif data.contains_simulated:
        story.append(_banner("Ce rapport ne contient que des DONNÉES SIMULÉES (mode laboratoire).", SIM_COLOR, st))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Résumé", st["h1"]))
    story.append(_table([[k, v] for k, v in data.summary_rows()], [60 * mm, 120 * mm], header=False, st=st))

    story.append(Paragraph("Équipements utilisés", st["h1"]))
    if data.devices:
        rows = [["Identifiant", "Libellé", "Fabricant / modèle", "Type", "Plage déclarée", "Nature"]]
        for d in data.devices:
            fr = ", ".join(f"{a / 1e6:.0f}–{b / 1e6:.0f} MHz" for a, b in d.get("freq_ranges_hz") or []) or "—"
            rows.append([d["id"], d["label"], f"{d['manufacturer']} / {d['model']}", d["backend"], fr,
                         "SIMULATION" if d["simulated"] else "MATÉRIEL RÉEL"])
        story.append(_table(rows, [30 * mm, 35 * mm, 40 * mm, 18 * mm, 32 * mm, 25 * mm], st=st))
    else:
        story.append(Paragraph("Aucune session de mesure sur la période.", st["body"]))

    story.append(Paragraph("Plages analysées et paramètres de mesure", st["h1"]))
    if data.ranges:
        rows = [["Session", "Plage analysée", "Centre", "Échantillonnage", "Gain", "Seuils de détection", "Nature"]]
        for r in data.ranges:
            det = r["detection"]
            rows.append([
                r["session"], f"{r['low_hz'] / 1e6:.4f} – {r['high_hz'] / 1e6:.4f} MHz", fmt_freq(r["center_hz"]),
                f"{r['sample_rate_hz'] / 1e3:.0f} kS/s", "auto" if r["gain_db"] is None else f"{r['gain_db']:.1f} dB",
                f"ouverture {det.get('open_threshold_db')} dB, maintien {det.get('close_threshold_db')} dB, "
                f"persistance {det.get('persistence_frames')} trames, durée min {det.get('min_duration_s')} s, "
                f"maintien {det.get('hang_time_s')} s",
                "SIMULATION" if r["simulated"] else "RÉEL",
            ])
        story.append(_table(rows, [13 * mm, 33 * mm, 24 * mm, 20 * mm, 13 * mm, 57 * mm, 20 * mm], st=st))

    if data.spectrum is not None:
        story.append(KeepTogether([
            Paragraph("Spectre de référence" + (" (maximum sur la session)" if data.spectrum.max_hold else ""),
                      st["h1"]),
            _spectrum_chart(data),
            Paragraph(_t(f"Instantané du {fmt_ts(data.spectrum.timestamp)} ; plancher de bruit "
                         f"{data.spectrum.noise_floor_dbfs:.1f} dBFS/case (pointillés)"
                         + (" ; SATURATION détectée" if data.spectrum.saturated else "")), st["small"]),
        ]))

    _event_section(story, "Événements détectés — mesures réelles", data.events_real, False, st)
    if data.events_simulated or data.contains_simulated:
        story.append(PageBreak())
        _event_section(story, "Événements détectés — données simulées", data.events_simulated, True, st)

    story.append(Paragraph("Résultats des tests", st["h1"]))
    if data.tests:
        rows = [["Date", "Test", "Résultat", "Nature", "Détails"]]
        for t in data.tests[-60:]:
            det = "; ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in t.details.items()
                            if not isinstance(v, dict))
            rows.append([fmt_ts(t.timestamp), t.name, "RÉUSSI" if t.passed else "ÉCHEC",
                         "SIMULATION" if t.simulated else "RÉEL", det[:300]])
        story.append(_table(rows, [25 * mm, 45 * mm, 15 * mm, 20 * mm, 75 * mm], st=st))
    else:
        story.append(Paragraph("Aucun test enregistré sur la période.", st["body"]))

    story.append(Paragraph("Erreurs", st["h1"]))
    if data.errors:
        story.append(_table([["Date", "Source", "Message"]] + [[fmt_ts(e["ts"]), e["source"], e["message"]]
                                                                for e in data.errors[-100:]],
                            [28 * mm, 25 * mm, 127 * mm], st=st))
    else:
        story.append(Paragraph("Aucune erreur enregistrée.", st["body"]))

    story.append(Paragraph("Limites techniques et précision des mesures", st["h1"]))
    for lim in data.limitations:
        story.append(Paragraph(_t("• " + lim), st["body"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(_t(
        "Logiciel en réception seule. Les résultats ne valent que pour la configuration décrite ; toute utilisation "
        "des informations reçues doit respecter la réglementation applicable (secret des correspondances, "
        "autorisations de réception et d'enregistrement)."), st["small"]))

    def _decorate(canvas, doc_) -> None:  # noqa: ANN001
        canvas.saveState()
        canvas.setFillColor(GRAPHITE)
        canvas.rect(0, A4[1] - 10 * mm, A4[0], 10 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(_FONT_BOLD, 8)
        canvas.drawString(15 * mm, A4[1] - 6.5 * mm, "LUNATIC RADIO LAB — rapport d'analyse")
        canvas.setFont(_FONT, 7)
        canvas.drawRightString(A4[0] - 15 * mm, A4[1] - 6.5 * mm, _d(fmt_ts(data.generated_ts)).replace("&amp;", "&"))
        canvas.setFillColor(colors.grey)
        canvas.drawString(15 * mm, 8 * mm, data.software)
        canvas.drawRightString(A4[0] - 15 * mm, 8 * mm, f"Page {doc_.page}")
        if data.contains_simulated and not data.contains_real:
            canvas.setFillColor(colors.Color(0.69, 0.29, 0.85, alpha=0.08))
            canvas.setFont(_FONT_BOLD, 60)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "SIMULATION")
        canvas.restoreState()

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return path
