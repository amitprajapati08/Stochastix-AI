"""
Durable audit/incident database. Deliberately SEPARATE from Redis:
Redis answers "what's happened in the last 60 seconds" and forgets on
purpose (TTL). This database answers "what happened, ever, and why" —
the record you'd need to defend a decision to a customer, an auditor,
or a judge. Two jobs, two stores, same "right tool for the job"
principle as the rest of Sentinel.

SQLite, not Postgres: no server to run, ships as one file, and nothing
here needs concurrent-write-at-scale for a prototype.
"""

import sqlite3
import json
from contextlib import contextmanager

DB_PATH = "sentinel_audit.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (
    merchant_id     TEXT PRIMARY KEY,
    name            TEXT,
    first_seen_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    device_fingerprint  TEXT PRIMARY KEY,
    first_seen_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    card_token      TEXT PRIMARY KEY,
    card_bin        TEXT,
    first_seen_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ip_addresses (
    ip_address      TEXT PRIMARY KEY,
    first_seen_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id      TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL,
    merchant_id         TEXT NOT NULL REFERENCES merchants(merchant_id),
    device_fingerprint  TEXT NOT NULL REFERENCES devices(device_fingerprint),
    card_token          TEXT NOT NULL REFERENCES cards(card_token),
    ip_address          TEXT NOT NULL REFERENCES ip_addresses(ip_address),
    amount              REAL NOT NULL,
    payment_method      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id      TEXT NOT NULL UNIQUE REFERENCES transactions(transaction_id),
    risk_probability    REAL NOT NULL,
    decision            TEXT NOT NULL CHECK (decision IN ('ALLOW','3DS_STEP_UP','BLOCK')),
    threshold_at_time   REAL NOT NULL,
    latency_ms          REAL NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at    TEXT NOT NULL,
    old_threshold   REAL NOT NULL,
    new_threshold   REAL NOT NULL,
    note            TEXT,
    cluster_summary TEXT,   -- JSON blob
    resolved_by     TEXT,
    resolved_at     TEXT
);

CREATE TABLE IF NOT EXISTS incident_transactions (
    incident_id     INTEGER NOT NULL REFERENCES incidents(incident_id),
    transaction_id  TEXT NOT NULL REFERENCES transactions(transaction_id),
    PRIMARY KEY (incident_id, transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_merchant ON transactions(merchant_id);
CREATE INDEX IF NOT EXISTS idx_transactions_device ON transactions(device_fingerprint);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_decision ON risk_decisions(decision);
"""


@contextmanager
def get_conn(path: str = DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str = DB_PATH):
    with get_conn(path) as conn:
        conn.executescript(SCHEMA)


def _upsert_dim(conn, table: str, pk_col: str, pk_val: str, now: str, extra: dict | None = None):
    """Insert a dimension row (merchant/device/card/ip) if it doesn't already exist."""
    cur = conn.execute(f"SELECT 1 FROM {table} WHERE {pk_col} = ?", (pk_val,))
    if cur.fetchone() is None:
        cols = [pk_col, "first_seen_at"] + (list(extra.keys()) if extra else [])
        vals = [pk_val, now] + (list(extra.values()) if extra else [])
        placeholders = ",".join("?" * len(cols))
        conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", vals)


def record_transaction_and_decision(conn, payload: dict, risk_probability: float,
                                     decision: str, threshold: float, latency_ms: float, now: str):
    _upsert_dim(conn, "merchants", "merchant_id", payload["merchant_id"], now)
    _upsert_dim(conn, "devices", "device_fingerprint", payload["device_fingerprint"], now)
    _upsert_dim(conn, "cards", "card_token", payload["card_token"], now, {"card_bin": payload.get("card_bin")})
    _upsert_dim(conn, "ip_addresses", "ip_address", payload["ip_address"], now)

    conn.execute(
        "INSERT OR IGNORE INTO transactions "
        "(transaction_id, timestamp, merchant_id, device_fingerprint, card_token, ip_address, amount, payment_method) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (payload["transaction_id"], now, payload["merchant_id"], payload["device_fingerprint"],
         payload["card_token"], payload["ip_address"], payload["amount"], payload.get("payment_method", "card")),
    )
    conn.execute(
        "INSERT INTO risk_decisions (transaction_id, risk_probability, decision, threshold_at_time, latency_ms, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (payload["transaction_id"], risk_probability, decision, threshold, latency_ms, now),
    )

def get_device_investigation_evidence(conn, device_fingerprint: str) -> dict:
    """Real, structured evidence pulled from the PERMANENT record — not
    just the current in-memory burst. This is what makes the investigator
    evidence-grounded rather than just summarizing what it was just told."""
    row = conn.execute(
        "SELECT COUNT(*) as total_txns, "
        "COUNT(DISTINCT merchant_id) as distinct_merchants, "
        "COUNT(DISTINCT card_token) as distinct_cards, "
        "MIN(timestamp) as first_seen "
        "FROM transactions WHERE device_fingerprint = ?",
        (device_fingerprint,),
    ).fetchone()
    block_count = conn.execute(
        "SELECT COUNT(*) FROM transactions t "
        "JOIN risk_decisions r ON r.transaction_id = t.transaction_id "
        "WHERE t.device_fingerprint = ? AND r.decision = 'BLOCK'",
        (device_fingerprint,),
    ).fetchone()[0]
    return {
        "device_fingerprint": device_fingerprint,
        "lifetime_transaction_count": row[0],
        "lifetime_distinct_merchants": row[1],
        "lifetime_distinct_cards": row[2],
        "first_seen_at": row[3],
        "lifetime_blocks": block_count,
    }

def record_incident(conn, triggered_at: str, old_threshold: float, new_threshold: float,
                     note: str, cluster_summary: dict, transaction_ids: list):
    cur = conn.execute(
        "INSERT INTO incidents (triggered_at, old_threshold, new_threshold, note, cluster_summary) "
        "VALUES (?,?,?,?,?)",
        (triggered_at, old_threshold, new_threshold, note, json.dumps(cluster_summary)),
    )
    incident_id = cur.lastrowid
    for txn_id in transaction_ids:
        conn.execute(
            "INSERT OR IGNORE INTO incident_transactions (incident_id, transaction_id) VALUES (?,?)",
            (incident_id, txn_id),
        )
    return incident_id
