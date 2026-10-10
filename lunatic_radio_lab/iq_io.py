"""Lecture/écriture de captures IQ au format SigMF (https://sigmf.org) ou brut.

Formats pris en charge : cf32_le (complex64), ci16_le (int16 entrelacé),
cu8 (uint8 entrelacé, sortie rtl_sdr). Les métadonnées propres à l'application
sont stockées sous l'espace de noms ``lrl:`` (dont ``lrl:simulated``).
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import __version__

DATATYPES = {"cf32_le": (np.complex64, 8), "ci16_le": (np.int16, 4), "cu8": (np.uint8, 2)}
MAX_META_BYTES = 2 * 1024 * 1024


@dataclass
class IQCapture:
    data_path: Path
    sample_rate: float
    center_freq: float
    datatype: str = "cf32_le"
    simulated: bool = False
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def num_samples(self) -> int:
        return self.data_path.stat().st_size // DATATYPES[self.datatype][1]

    @property
    def duration_s(self) -> float:
        return self.num_samples / self.sample_rate

    def read(self, start: int = 0, count: int | None = None) -> np.ndarray:
        dtype, size = DATATYPES[self.datatype]
        total = self.num_samples
        if count is None:
            count = total - start
        count = max(0, min(count, total - start))
        with open(self.data_path, "rb") as fh:
            fh.seek(start * size)
            raw = np.frombuffer(fh.read(count * size), dtype=dtype)
        return convert_raw(raw, self.datatype)


def convert_raw(raw: np.ndarray, datatype: str) -> np.ndarray:
    if datatype == "cf32_le":
        return raw.astype(np.complex64, copy=False)
    if datatype == "ci16_le":
        f = raw.astype(np.float32) / 32768.0
    elif datatype == "cu8":
        f = (raw.astype(np.float32) - 127.5) / 127.5
    else:
        raise ValueError(f"Type de données IQ inconnu : {datatype}")
    return (f[0::2] + 1j * f[1::2]).astype(np.complex64)


def write_sigmf(
    base_path: str | Path,
    iq: np.ndarray,
    sample_rate: float,
    center_freq: float,
    simulated: bool,
    description: str = "",
    hw: str = "",
    extra: dict[str, Any] | None = None,
    annotations: list[dict[str, Any]] | None = None,
) -> IQCapture:
    base = Path(base_path)
    if base.suffix in (".sigmf-data", ".sigmf-meta"):
        base = base.with_suffix("")
    data_path = base.with_suffix(".sigmf-data")
    meta_path = base.with_suffix(".sigmf-meta")
    np.asarray(iq, dtype=np.complex64).tofile(data_path)
    meta = {
        "global": {
            "core:datatype": "cf32_le",
            "core:sample_rate": float(sample_rate),
            "core:version": "1.0.0",
            "core:description": description,
            "core:recorder": f"LUNATIC RADIO LAB {__version__}",
            "core:hw": hw,
            "lrl:simulated": bool(simulated),
            **(extra or {}),
        },
        "captures": [
            {
                "core:sample_start": 0,
                "core:frequency": float(center_freq),
                "core:datetime": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        ],
        "annotations": annotations or [],
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return IQCapture(data_path, sample_rate, center_freq, "cf32_le", simulated, description, extra or {})


def read_sigmf(path: str | Path) -> IQCapture:
    p = Path(path)
    meta_path = p.with_suffix(".sigmf-meta")
    data_path = p.with_suffix(".sigmf-data")
    if meta_path.stat().st_size > MAX_META_BYTES:
        raise ValueError("Fichier de métadonnées SigMF trop volumineux")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict) or "global" not in meta:
        raise ValueError("Métadonnées SigMF invalides (section « global » absente)")
    g = meta["global"]
    dt = str(g.get("core:datatype", ""))
    if dt not in DATATYPES:
        raise ValueError(f"Type SigMF non pris en charge : {dt} (pris en charge : {', '.join(DATATYPES)})")
    sr = float(g.get("core:sample_rate", 0))
    if sr <= 0:
        raise ValueError("core:sample_rate manquant ou invalide")
    caps = meta.get("captures") or [{}]
    fc = float(caps[0].get("core:frequency", 0.0))
    if not data_path.exists():
        raise FileNotFoundError(f"Fichier de données absent : {data_path.name}")
    extra = {k: v for k, v in g.items() if k.startswith("lrl:")}
    return IQCapture(data_path, sr, fc, dt, bool(g.get("lrl:simulated", False)), str(g.get("core:description", "")),
                     extra)


def open_raw(path: str | Path, sample_rate: float, center_freq: float, datatype: str = "cf32_le") -> IQCapture:
    if datatype not in DATATYPES:
        raise ValueError(f"Type de données inconnu : {datatype}")
    p = Path(path)
    if p.stat().st_size % DATATYPES[datatype][1]:
        raise ValueError("Taille de fichier incompatible avec le type de données choisi")
    return IQCapture(p, sample_rate, center_freq, datatype)
