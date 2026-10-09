from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Generator

DB_PATH = Path(
    os.environ.get(
        "ROUTE53_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "route53.db"),
    )
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return f"pbkdf2_sha256$260000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hosted_zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            comment TEXT,
            zone_type TEXT NOT NULL DEFAULT 'public',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            owner_id INTEGER NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(hosted_zones)")}
    if "zone_type" not in columns:
        conn.execute("ALTER TABLE hosted_zones ADD COLUMN zone_type TEXT NOT NULL DEFAULT 'public'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dns_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            ttl INTEGER NOT NULL DEFAULT 300,
            value TEXT,
            priority INTEGER,
            weight INTEGER,
            port INTEGER,
            target TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(zone_id) REFERENCES hosted_zones(id) ON DELETE CASCADE
        )
        """
    )

    if conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone() is None:
        conn.execute(
            "INSERT INTO users (username, password, role, name) VALUES (?, ?, ?, ?)",
            ("admin", hash_password("admin123"), "admin", "Demo Admin"),
        )
    for user in conn.execute("SELECT id, password FROM users").fetchall():
        if not user["password"].startswith("pbkdf2_sha256$"):
            conn.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (hash_password(user["password"]), user["id"]),
            )

    if conn.execute("SELECT id FROM hosted_zones LIMIT 1").fetchone() is None:
        admin_id = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()["id"]
        for name, comment in (
            ("example.com", "Primary production zone"),
            ("demo.net", "Staging domain zone"),
            ("acme.io", "Customer-facing zone"),
        ):
            now = utc_now()
            zone_id = conn.execute(
                "INSERT INTO hosted_zones (name, comment, zone_type, owner_id, created_at, updated_at) "
                "VALUES (?, ?, 'public', ?, ?, ?)",
                (f"{name}.", comment, admin_id, now, now),
            ).lastrowid
            sample_records = [
                ("@", "A", 300, "192.0.2.10", None, None, None, None),
                ("www", "CNAME", 300, "example.com.", None, None, None, None),
                ("mail", "MX", 300, "mail.example.com.", 10, None, None, None),
                ("_sip._tcp", "SRV", 300, "sip.example.com.", 10, 5, 5060, "sip.example.com."),
            ]
            conn.executemany(
                "INSERT INTO dns_records "
                "(zone_id, name, type, ttl, value, priority, weight, port, target, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (zone_id, *record, now, now)
                    for record in sample_records
                ],
            )

    for zone in conn.execute("SELECT id, name FROM hosted_zones").fetchall():
        for record in conn.execute(
            "SELECT id, name FROM dns_records WHERE zone_id = ?",
            (zone["id"],),
        ).fetchall():
            if record["name"] == "@" or not record["name"].endswith("."):
                name = zone["name"].rstrip(".") if record["name"] == "@" else f"{record['name']}.{zone['name'].rstrip('.')}"
                conn.execute("UPDATE dns_records SET name = ? WHERE id = ?", (f"{name}.", record["id"]))

    conn.commit()
    conn.close()
