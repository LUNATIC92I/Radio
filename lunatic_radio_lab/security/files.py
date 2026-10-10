"""Import sécurisé de fichiers (audio, captures IQ, scénarios, canaux).

Contrôles : fichier régulier (pas de lien symbolique ni de périphérique), extension
autorisée, taille maximale, signature (« magic bytes ») cohérente, nom assaini,
copie en lecture seule dans le répertoire d'imports avec empreinte SHA-256.
Les fichiers ne sont jamais exécutés.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from .. import paths

MB = 1024 * 1024

KINDS: dict[str, dict] = {
    "audio": {"ext": {".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a"}, "max": 500 * MB},
    "iq": {"ext": {".sigmf-meta", ".sigmf-data", ".cfile", ".cf32", ".cs16", ".cu8", ".bin", ".raw"}, "max": 4096 * MB},
    "json": {"ext": {".json"}, "max": 5 * MB},
    "csv": {"ext": {".csv"}, "max": 20 * MB},
}


class ImportRejected(ValueError):
    pass


@dataclass
class ImportedFile:
    path: Path
    original_name: str
    sha256: str
    size: int
    kind: str


def sanitize_filename(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "fichier"
    return base[:120]


def _ext(p: Path) -> str:
    n = p.name.lower()
    for e in (".sigmf-meta", ".sigmf-data"):
        if n.endswith(e):
            return e
    return p.suffix.lower()


def _check_magic(p: Path, ext: str) -> None:
    with open(p, "rb") as fh:
        head = fh.read(16)
    if ext == ".wav" and not (head[:4] in (b"RIFF", b"RF64") and head[8:12] == b"WAVE"):
        raise ImportRejected("En-tête WAV invalide (signature RIFF/WAVE absente).")
    if ext == ".flac" and head[:4] != b"fLaC":
        raise ImportRejected("En-tête FLAC invalide.")
    if ext in (".ogg", ".opus") and head[:4] != b"OggS":
        raise ImportRejected("En-tête Ogg invalide.")
    if ext in (".json", ".sigmf-meta"):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImportRejected(f"JSON invalide : {exc}") from exc
    if ext == ".csv":
        try:
            p.open(encoding="utf-8").read(4096)
        except UnicodeDecodeError as exc:
            raise ImportRejected("Le CSV doit être encodé en UTF-8.") from exc


def validate_file(path: str | Path, kind: str) -> tuple[Path, int, str]:
    if kind not in KINDS:
        raise ImportRejected(f"Type d'import inconnu : {kind}")
    p = Path(path)
    try:
        st = os.lstat(p)
    except OSError as exc:
        raise ImportRejected(f"Fichier inaccessible : {exc}") from exc
    if stat.S_ISLNK(st.st_mode):
        raise ImportRejected("Les liens symboliques ne sont pas acceptés.")
    if not stat.S_ISREG(st.st_mode):
        raise ImportRejected("Seuls les fichiers réguliers sont acceptés.")
    ext = _ext(p)
    if ext not in KINDS[kind]["ext"]:
        raise ImportRejected(f"Extension « {ext} » non autorisée pour un import {kind} "
                             f"({', '.join(sorted(KINDS[kind]['ext']))}).")
    if st.st_size == 0:
        raise ImportRejected("Fichier vide.")
    if st.st_size > KINDS[kind]["max"]:
        raise ImportRejected(f"Fichier trop volumineux ({st.st_size / MB:.1f} Mo, max {KINDS[kind]['max'] / MB:.0f} Mo).")
    _check_magic(p, ext)
    return p.resolve(), st.st_size, ext


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(MB), b""):
            h.update(chunk)
    return h.hexdigest()


def secure_import(path: str | Path, kind: str, dest_dir: Path | None = None) -> ImportedFile:
    src, size, _ = validate_file(path, kind)
    digest = sha256_file(src)
    dest_dir = dest_dir or paths.imports_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = sanitize_filename(src.name)
    dest = dest_dir / f"{digest[:12]}_{name}"
    if not dest.exists():
        shutil.copyfile(src, dest)
        os.chmod(dest, 0o444)
    return ImportedFile(dest, src.name, digest, size, kind)


def secure_import_sigmf(meta_or_data: str | Path, dest_dir: Path | None = None) -> ImportedFile:
    """Importe une paire SigMF (.sigmf-meta + .sigmf-data) en conservant l'appariement."""
    p = Path(meta_or_data)
    stem = p.name[: -len(_ext(p))] if _ext(p) in (".sigmf-meta", ".sigmf-data") else p.stem
    meta = p.with_name(stem + ".sigmf-meta")
    data = p.with_name(stem + ".sigmf-data")
    m_src, _, _ = validate_file(meta, "iq")
    if m_src.stat().st_size > 2 * MB:
        raise ImportRejected("Métadonnées SigMF trop volumineuses.")
    d_src, size, _ = validate_file(data, "iq")
    digest = sha256_file(d_src)
    folder = (dest_dir or paths.imports_dir()) / f"sigmf_{digest[:12]}"
    folder.mkdir(parents=True, exist_ok=True)
    base = sanitize_filename(stem)
    out_meta, out_data = folder / f"{base}.sigmf-meta", folder / f"{base}.sigmf-data"
    for s, d in ((m_src, out_meta), (d_src, out_data)):
        if not d.exists():
            shutil.copyfile(s, d)
            os.chmod(d, 0o444)
    return ImportedFile(out_meta, meta.name, digest, size, "iq")
