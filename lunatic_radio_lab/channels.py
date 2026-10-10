"""Gestion des canaux de test autorisés.

L'administrateur y enregistre les canaux qu'il est autorisé à surveiller (bande,
largeur, usage, équipement, référence d'autorisation). Le logiciel ne fournit
aucune liste de fréquences sensibles ; seul le plan PMR446 (public, sans licence
dans l'UE) est proposé à l'import.

Le logiciel reste en RÉCEPTION SEULE : un canal ne permet jamais d'émettre.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .dsp.activity import ChannelWindow
from .models import DeviceInfo
from .protocols.profiles import PROFILES, bands_containing, pmr446_channel_plan
from .security.access import AccessController
from .storage.database import Database

MIN_BW_HZ = 100.0
MAX_BW_HZ = 10e6
MIN_FREQ_HZ = 9e3
MAX_FREQ_HZ = 300e9


@dataclass
class AuthorizedChannel:
    name: str
    center_freq_hz: float
    bandwidth_hz: float
    usage: str = ""
    equipment: str = ""
    profile_id: str | None = None
    jurisdiction: str = ""
    authorization_ref: str = ""
    recording_allowed: bool = False
    notes: str = ""
    id: int | None = None

    @property
    def low_hz(self) -> float:
        return self.center_freq_hz - self.bandwidth_hz / 2

    @property
    def high_hz(self) -> float:
        return self.center_freq_hz + self.bandwidth_hz / 2

    def to_window(self) -> ChannelWindow:
        return ChannelWindow(self.name, self.center_freq_hz, self.bandwidth_hz)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuthorizedChannel:
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        known["center_freq_hz"] = float(known["center_freq_hz"])
        known["bandwidth_hz"] = float(known["bandwidth_hz"])
        known["recording_allowed"] = str(known.get("recording_allowed", False)).lower() in ("1", "true", "oui", "yes")
        if known.get("profile_id") == "":
            known["profile_id"] = None
        return cls(**known)


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_channel(
    ch: AuthorizedChannel,
    existing: list[AuthorizedChannel] | None = None,
    device: DeviceInfo | None = None,
    sample_rate_hz: float | None = None,
) -> ValidationReport:
    r = ValidationReport()
    if not ch.name.strip():
        r.errors.append("Le nom du canal est obligatoire.")
    if len(ch.name) > 64:
        r.errors.append("Nom trop long (64 caractères maximum).")
    if not MIN_FREQ_HZ <= ch.center_freq_hz <= MAX_FREQ_HZ:
        r.errors.append("Fréquence centrale hors de la plage radioélectrique admise (9 kHz – 300 GHz).")
    if not MIN_BW_HZ <= ch.bandwidth_hz <= MAX_BW_HZ:
        r.errors.append(f"Largeur de bande invalide ({MIN_BW_HZ:.0f} Hz – {MAX_BW_HZ / 1e6:.0f} MHz).")
    if ch.profile_id and ch.profile_id not in PROFILES:
        r.errors.append(f"Profil inconnu : {ch.profile_id}")
    for other in existing or []:
        if other.id is not None and other.id == ch.id:
            continue
        if other.name.strip().lower() == ch.name.strip().lower():
            r.errors.append(f"Un canal nommé « {other.name} » existe déjà.")
        elif ch.low_hz < other.high_hz and other.low_hz < ch.high_hz:
            r.warnings.append(f"Chevauchement avec le canal « {other.name} ».")
    if ch.profile_id and ch.profile_id in PROFILES:
        p = PROFILES[ch.profile_id]
        if p.channel_spacing_hz and abs(ch.bandwidth_hz - p.channel_spacing_hz) > 0.01 * p.channel_spacing_hz:
            r.warnings.append(f"Largeur {ch.bandwidth_hz:.0f} Hz différente de la canalisation du profil "
                              f"« {p.name} » ({p.channel_spacing_hz:.0f} Hz).")
    if device is not None:
        if device.freq_ranges_hz and not (device.supports_frequency(ch.low_hz) and device.supports_frequency(ch.high_hz)):
            r.warnings.append(f"Le canal dépasse les capacités du récepteur « {device.label} » "
                              f"({device.frequency_summary()}).")
        if device.sample_rates_hz and max(device.sample_rates_hz) < ch.bandwidth_hz:
            r.warnings.append("La largeur du canal dépasse la fréquence d'échantillonnage maximale du récepteur.")
    if sample_rate_hz and ch.bandwidth_hz > 0.8 * sample_rate_hz:
        r.warnings.append("Canal plus large que 80 % de la bande observée : mesures en bord de bande dégradées.")
    lic_free = [b for _, b in bands_containing(ch.center_freq_hz)]
    if lic_free:
        r.warnings.append(f"Bande documentée : {lic_free[0].note} Vérification réglementaire locale requise.")
    else:
        r.warnings.append("Vérification réglementaire requise : assurez-vous de disposer d'une autorisation de "
                          "réception/écoute pour ce canal dans votre juridiction.")
    if not ch.authorization_ref.strip():
        r.warnings.append("Aucune référence d'autorisation saisie (licence, convention, ordre de mission…).")
    if ch.recording_allowed and not ch.authorization_ref.strip():
        r.errors.append("L'enregistrement audio exige une référence d'autorisation documentée.")
    return r


class ChannelManager:
    def __init__(self, db: Database, access: AccessController):
        self.db = db
        self.access = access

    def list(self) -> list[AuthorizedChannel]:
        return [AuthorizedChannel.from_dict(d) for d in self.db.list_channels()]

    def get(self, cid: int) -> AuthorizedChannel | None:
        return next((c for c in self.list() if c.id == cid), None)

    def save(self, ch: AuthorizedChannel, device: DeviceInfo | None = None) -> ValidationReport:
        rep = validate_channel(ch, self.list(), device)
        if not rep.ok:
            return rep
        prev = self.get(ch.id) if ch.id else None
        self.access.require("channels.edit", {"name": ch.name, "freq_hz": ch.center_freq_hz})
        if ch.recording_allowed and not (prev and prev.recording_allowed):
            self.access.require("recording.authorize", {"name": ch.name, "ref": ch.authorization_ref})
        ch.id = self.db.upsert_channel(ch.to_dict())
        return rep

    def delete(self, cid: int) -> None:
        ch = self.get(cid)
        self.access.require("channels.delete", {"id": cid, "name": ch.name if ch else None})
        self.db.delete_channel(cid)

    def import_pmr446(self) -> int:
        existing = {c.name for c in self.list()}
        n = 0
        for name, f, bw in pmr446_channel_plan():
            if name in existing:
                continue
            ch = AuthorizedChannel(name, f, bw, usage="PMR446 analogique (sans licence UE)", profile_id="pmr446_analog",
                                   jurisdiction="UE/CEPT", authorization_ref="ECC/DEC/(15)05 — usage libre PMR446",
                                   notes="Plan de canaux public. Vérifier la réglementation nationale.")
            if self.save(ch).ok:
                n += 1
        return n

    def windows(self) -> list[ChannelWindow]:
        return [c.to_window() for c in self.list()]

    def channel_at(self, freq_hz: float) -> AuthorizedChannel | None:
        for c in self.list():
            if c.low_hz <= freq_hz <= c.high_hz:
                return c
        return None

    def recording_permitted(self, low_hz: float, high_hz: float) -> AuthorizedChannel | None:
        """Canal autorisant l'enregistrement couvrant entièrement [low, high], sinon None."""
        for c in self.list():
            if c.recording_allowed and c.low_hz <= low_hz and high_hz <= c.high_hz:
                return c
        return None

    def monitor_authorization(self, freq_hz: float, bandwidth_hz: float, simulated: bool,
                              record: bool) -> tuple[bool, AuthorizedChannel | None, str]:
        """Règle d'écoute/enregistrement en direct.

        * données simulées : toujours permis (aucune communication réelle) ;
        * données réelles : le canal écouté doit être entièrement couvert par un canal autorisé
          portant une référence d'autorisation ; l'enregistrement exige en plus l'option
          « enregistrement autorisé ».
        """
        if simulated:
            return True, None, "Données simulées : aucune communication réelle."
        lo, hi = freq_hz - bandwidth_hz / 2, freq_hz + bandwidth_hz / 2
        cands = [c for c in self.list() if c.low_hz <= lo and hi <= c.high_hz]
        if not cands:
            return False, None, (f"{freq_hz / 1e6:.5f} MHz n'est couvert par aucun canal autorisé. "
                                 "Un administrateur doit d'abord enregistrer ce canal.")
        ch = next((c for c in cands if c.authorization_ref.strip()), None)
        if ch is None:
            return False, cands[0], f"Le canal « {cands[0].name} » n'a pas de référence d'autorisation."
        if record and not ch.recording_allowed:
            return False, ch, f"L'enregistrement n'est pas autorisé sur le canal « {ch.name} »."
        return True, ch, f"Canal autorisé : {ch.name} ({ch.authorization_ref})"

    # --------------------------------------------------------------- import / export
    def export_json(self) -> str:
        return json.dumps([c.to_dict() for c in self.list()], indent=2, ensure_ascii=False)

    def export_csv(self) -> str:
        buf = io.StringIO()
        fields = list(AuthorizedChannel.__dataclass_fields__)
        w = csv.DictWriter(buf, fieldnames=fields)
        w.writeheader()
        for c in self.list():
            w.writerow(c.to_dict())
        return buf.getvalue()

    def import_records(self, records: list[dict[str, Any]]) -> tuple[int, list[str]]:
        ok, problems = 0, []
        for i, rec in enumerate(records):
            try:
                rec = {k: v for k, v in rec.items() if k != "id"}
                ch = AuthorizedChannel.from_dict(rec)
            except (KeyError, ValueError, TypeError) as exc:
                problems.append(f"Ligne {i + 1} : enregistrement invalide ({exc}).")
                continue
            rep = self.save(ch)
            if rep.ok:
                ok += 1
            else:
                problems.append(f"{ch.name} : " + " ".join(rep.errors))
        return ok, problems
