"""Contrôle d'accès aux paramètres sensibles (code administrateur) et journal d'audit.

Le code est stocké sous forme de dérivé PBKDF2-HMAC-SHA256 salé (jamais en clair).
Après plusieurs échecs, le déverrouillage est temporairement bloqué. Le
déverrouillage expire automatiquement.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from contextlib import contextmanager
from typing import Callable, Iterator

from ..storage.database import Database

PBKDF2_ITERATIONS = 240_000
MIN_PIN_LENGTH = 6
MAX_FAILURES = 5
LOCKOUT_S = 60.0
DEFAULT_UNLOCK_S = 600.0

# Actions nécessitant le déverrouillage administrateur
SENSITIVE_ACTIONS = {
    "channels.edit": "Modifier les canaux autorisés",
    "channels.delete": "Supprimer un canal autorisé",
    "recording.authorize": "Autoriser l'enregistrement sur un canal",
    "calibration.edit": "Modifier l'étalonnage de puissance",
    "history.purge": "Purger l'historique",
    "network.devices": "Autoriser les récepteurs réseau",
    "jurisdiction.edit": "Modifier la juridiction réglementaire",
    "admin.pin": "Changer le code administrateur",
}


class AccessDenied(PermissionError):
    pass


def hash_pin(pin: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        algo, it, salt_hex, dk_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), int(it))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, TypeError):
        return False


class AccessController:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time):
        self.db = db
        self.clock = clock
        self._unlocked_until = 0.0
        self._failures = 0
        self._locked_until = 0.0
        self.actor = "opérateur"

    @property
    def has_pin(self) -> bool:
        return bool(self.db.get_setting("admin_pin_hash"))

    @property
    def unlocked(self) -> bool:
        return self.clock() < self._unlocked_until

    @property
    def remaining_s(self) -> float:
        return max(0.0, self._unlocked_until - self.clock())

    def set_pin(self, new_pin: str, current_pin: str | None = None) -> None:
        if len(new_pin) < MIN_PIN_LENGTH:
            raise ValueError(f"Le code doit contenir au moins {MIN_PIN_LENGTH} caractères.")
        if self.has_pin:
            if current_pin is None or not verify_pin(current_pin, self.db.get_setting("admin_pin_hash")):
                self.db.audit(self.actor, "admin.pin", {"result": "code actuel invalide"}, success=False)
                raise AccessDenied("Code administrateur actuel invalide.")
        self.db.set_setting("admin_pin_hash", hash_pin(new_pin))
        self.db.audit(self.actor, "admin.pin", {"result": "code défini"})

    def unlock(self, pin: str, duration_s: float = DEFAULT_UNLOCK_S) -> bool:
        now = self.clock()
        if now < self._locked_until:
            self.db.audit(self.actor, "admin.unlock", {"result": "bloqué (trop d'échecs)"}, success=False)
            raise AccessDenied(f"Trop d'essais : réessayez dans {int(self._locked_until - now)} s.")
        stored = self.db.get_setting("admin_pin_hash")
        if not stored:
            raise AccessDenied("Aucun code administrateur défini : définissez-en un d'abord.")
        if verify_pin(pin, stored):
            self._failures = 0
            self._unlocked_until = now + duration_s
            self.db.audit(self.actor, "admin.unlock", {"duration_s": duration_s})
            return True
        self._failures += 1
        if self._failures >= MAX_FAILURES:
            self._locked_until = now + LOCKOUT_S
            self._failures = 0
        self.db.audit(self.actor, "admin.unlock", {"result": "code invalide"}, success=False)
        return False

    def lock(self) -> None:
        if self.unlocked:
            self.db.audit(self.actor, "admin.lock", {})
        self._unlocked_until = 0.0

    def require(self, action: str, details: dict | None = None) -> None:
        """Vérifie le droit d'effectuer une action sensible et la journalise."""
        if action in SENSITIVE_ACTIONS and not self.unlocked:
            self.db.audit(self.actor, action, {**(details or {}), "result": "refusé (verrouillé)"}, success=False)
            raise AccessDenied(f"Action protégée : « {SENSITIVE_ACTIONS[action]} ». Déverrouillez l'accès administrateur.")
        self.db.audit(self.actor, action, details or {})

    @contextmanager
    def elevated(self, reason: str) -> Iterator[None]:
        """Élévation temporaire pour une opération locale non interactive (CLI, données de démonstration).

        Journalisée dans l'audit ; à ne pas exposer dans l'interface graphique.
        """
        self.db.audit("système", "admin.elevate", {"reason": reason})
        prev = self._unlocked_until
        self._unlocked_until = self.clock() + 3600.0
        try:
            yield
        finally:
            self._unlocked_until = prev
