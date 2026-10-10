"""Stockage local SQLite : paramètres, canaux autorisés, événements, tests, journal d'audit."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from ..models import ActivityEvent, TestResult

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    center_freq_hz REAL NOT NULL,
    bandwidth_hz REAL NOT NULL,
    usage TEXT NOT NULL DEFAULT '',
    equipment TEXT NOT NULL DEFAULT '',
    profile_id TEXT,
    jurisdiction TEXT NOT NULL DEFAULT '',
    authorization_ref TEXT NOT NULL DEFAULT '',
    recording_allowed INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts REAL NOT NULL,
    end_ts REAL,
    receiver_id TEXT NOT NULL,
    receiver_label TEXT NOT NULL,
    simulated INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    detection_json TEXT NOT NULL,
    device_json TEXT NOT NULL DEFAULT '{}',
    scenario TEXT,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    receiver_id TEXT NOT NULL,
    tuned_freq_hz REAL NOT NULL,
    emission_freq_hz REAL NOT NULL,
    channel_name TEXT,
    channel_freq_hz REAL,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    duration_s REAL NOT NULL,
    peak_power_dbfs REAL NOT NULL,
    mean_power_dbfs REAL NOT NULL,
    snr_db REAL NOT NULL,
    bandwidth_hz REAL,
    freq_std_hz REAL NOT NULL,
    frames INTEGER NOT NULL,
    detection_json TEXT NOT NULL,
    simulated INTEGER NOT NULL,
    classification TEXT,
    classification_confidence REAL,
    kind TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_ts);
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    name TEXT NOT NULL,
    passed INTEGER NOT NULL,
    receiver_id TEXT NOT NULL,
    simulated INTEGER NOT NULL,
    details_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    session_id INTEGER
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    details_json TEXT NOT NULL,
    success INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.executescript(SCHEMA)
            self.conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    # ------------------------------------------------------------------ paramètres
    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self._query("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_setting(self, key: str, value: Any) -> None:
        self._exec("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                   (key, json.dumps(value)))

    def all_settings(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self._query("SELECT key, value FROM settings")}

    # ------------------------------------------------------------------ canaux
    def upsert_channel(self, ch: dict[str, Any]) -> int:
        now = time.time()
        fields = ("name", "center_freq_hz", "bandwidth_hz", "usage", "equipment", "profile_id", "jurisdiction",
                  "authorization_ref", "recording_allowed", "notes")
        vals = [ch.get(f) for f in fields]
        vals[8] = int(bool(vals[8]))
        for i, f in enumerate(fields):
            if vals[i] is None and f not in ("profile_id",):
                vals[i] = ""
        if ch.get("id"):
            self._exec(
                f"UPDATE channels SET {', '.join(f + ' = ?' for f in fields)}, updated_ts = ? WHERE id = ?",
                [*vals, now, ch["id"]],
            )
            return int(ch["id"])
        cur = self._exec(
            f"INSERT INTO channels({', '.join(fields)}, created_ts, updated_ts) VALUES({', '.join('?' * len(fields))}, ?, ?)",
            [*vals, now, now],
        )
        return int(cur.lastrowid)

    def delete_channel(self, cid: int) -> None:
        self._exec("DELETE FROM channels WHERE id = ?", (cid,))

    def list_channels(self) -> list[dict[str, Any]]:
        rows = self._query("SELECT * FROM channels ORDER BY center_freq_hz")
        out = []
        for r in rows:
            d = dict(r)
            d["recording_allowed"] = bool(d["recording_allowed"])
            out.append(d)
        return out

    # ------------------------------------------------------------------ sessions
    def start_session(self, receiver_id: str, receiver_label: str, simulated: bool, config: dict, detection: dict,
                      device: dict | None = None, scenario: str | None = None) -> int:
        cur = self._exec(
            "INSERT INTO sessions(start_ts, receiver_id, receiver_label, simulated, config_json, detection_json, "
            "device_json, scenario) VALUES(?,?,?,?,?,?,?,?)",
            (time.time(), receiver_id, receiver_label, int(simulated), json.dumps(config), json.dumps(detection),
             json.dumps(device or {}, default=str), scenario),
        )
        return int(cur.lastrowid)

    def end_session(self, sid: int) -> None:
        self._exec("UPDATE sessions SET end_ts = ? WHERE id = ?", (time.time(), sid))

    def list_sessions(self, since: float | None = None, until: float | None = None) -> list[dict[str, Any]]:
        sql, p = "SELECT * FROM sessions WHERE 1=1", []
        if since is not None:
            sql += " AND COALESCE(end_ts, start_ts) >= ?"
            p.append(since)
        if until is not None:
            sql += " AND start_ts <= ?"
            p.append(until)
        out = []
        for r in self._query(sql + " ORDER BY start_ts", p):
            d = dict(r)
            d["simulated"] = bool(d["simulated"])
            d["config"] = json.loads(d.pop("config_json"))
            d["detection"] = json.loads(d.pop("detection_json"))
            d["device"] = json.loads(d.pop("device_json") or "{}")
            out.append(d)
        return out

    # ------------------------------------------------------------------ événements
    def add_event(self, ev: ActivityEvent, session_id: int | None = None) -> int:
        cur = self._exec(
            "INSERT INTO events(session_id, receiver_id, tuned_freq_hz, emission_freq_hz, channel_name, channel_freq_hz,"
            " start_ts, end_ts, duration_s, peak_power_dbfs, mean_power_dbfs, snr_db, bandwidth_hz, freq_std_hz, frames,"
            " detection_json, simulated, classification, classification_confidence, kind)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, ev.receiver_id, ev.tuned_freq_hz, ev.emission_freq_hz, ev.channel_name, ev.channel_freq_hz,
             ev.start_ts, ev.end_ts, ev.duration_s, ev.peak_power_dbfs, ev.mean_power_dbfs, ev.snr_db, ev.bandwidth_hz,
             ev.freq_std_hz, ev.frames, json.dumps(ev.detection_params), int(ev.simulated), ev.classification,
             ev.classification_confidence, ev.kind),
        )
        ev.id = int(cur.lastrowid)
        return ev.id

    def update_event_classification(self, eid: int, label: str, confidence: float) -> None:
        self._exec("UPDATE events SET classification = ?, classification_confidence = ? WHERE id = ?",
                   (label, confidence, eid))

    def query_events(
        self,
        since: float | None = None,
        until: float | None = None,
        simulated: bool | None = None,
        min_freq: float | None = None,
        max_freq: float | None = None,
        min_power: float | None = None,
        channel: str | None = None,
        min_duration: float | None = None,
        limit: int = 10_000,
    ) -> list[ActivityEvent]:
        sql, p = "SELECT * FROM events WHERE 1=1", []
        for cond, val in (
            ("start_ts >= ?", since), ("start_ts <= ?", until), ("emission_freq_hz >= ?", min_freq),
            ("emission_freq_hz <= ?", max_freq), ("peak_power_dbfs >= ?", min_power), ("channel_name = ?", channel),
            ("duration_s >= ?", min_duration),
        ):
            if val is not None:
                sql += f" AND {cond}"
                p.append(val)
        if simulated is not None:
            sql += " AND simulated = ?"
            p.append(int(simulated))
        sql += " ORDER BY start_ts DESC LIMIT ?"
        p.append(int(limit))
        return [self._row_to_event(r) for r in self._query(sql, p)]

    @staticmethod
    def _row_to_event(r: sqlite3.Row) -> ActivityEvent:
        return ActivityEvent(
            receiver_id=r["receiver_id"], tuned_freq_hz=r["tuned_freq_hz"], emission_freq_hz=r["emission_freq_hz"],
            start_ts=r["start_ts"], end_ts=r["end_ts"], peak_power_dbfs=r["peak_power_dbfs"],
            mean_power_dbfs=r["mean_power_dbfs"], snr_db=r["snr_db"], bandwidth_hz=r["bandwidth_hz"],
            freq_std_hz=r["freq_std_hz"], detection_params=json.loads(r["detection_json"]),
            simulated=bool(r["simulated"]), channel_name=r["channel_name"], channel_freq_hz=r["channel_freq_hz"],
            frames=r["frames"], classification=r["classification"],
            classification_confidence=r["classification_confidence"], id=r["id"], kind=r["kind"],
        )

    def purge_events(self, before_ts: float | None = None) -> int:
        if before_ts is None:
            return self._exec("DELETE FROM events").rowcount
        return self._exec("DELETE FROM events WHERE start_ts < ?", (before_ts,)).rowcount

    # ------------------------------------------------------------------ tests / erreurs
    def add_test_result(self, t: TestResult) -> int:
        cur = self._exec(
            "INSERT INTO test_results(ts, name, passed, receiver_id, simulated, details_json) VALUES(?,?,?,?,?,?)",
            (t.timestamp, t.name, int(t.passed), t.receiver_id, int(t.simulated), json.dumps(t.details, default=str)),
        )
        t.id = int(cur.lastrowid)
        return t.id

    def list_test_results(self, since: float | None = None) -> list[TestResult]:
        rows = self._query("SELECT * FROM test_results WHERE ts >= ? ORDER BY ts", (since or 0.0,))
        return [TestResult(r["name"], bool(r["passed"]), json.loads(r["details_json"]), bool(r["simulated"]),
                           r["receiver_id"], r["ts"], r["id"]) for r in rows]

    def log_error(self, source: str, message: str, session_id: int | None = None) -> None:
        self._exec("INSERT INTO errors(ts, source, message, session_id) VALUES(?,?,?,?)",
                   (time.time(), source, message, session_id))

    def list_errors(self, since: float | None = None) -> list[dict[str, Any]]:
        return [dict(r) for r in self._query("SELECT * FROM errors WHERE ts >= ? ORDER BY ts", (since or 0.0,))]

    # ------------------------------------------------------------------ audit
    def audit(self, actor: str, action: str, details: dict | None = None, success: bool = True) -> None:
        self._exec("INSERT INTO audit_log(ts, actor, action, details_json, success) VALUES(?,?,?,?,?)",
                   (time.time(), actor, action, json.dumps(details or {}, default=str), int(success)))

    def list_audit(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            d["details"] = json.loads(d.pop("details_json"))
            d["success"] = bool(d["success"])
            out.append(d)
        return out
