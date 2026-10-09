from __future__ import annotations

import json
import ipaddress
import os
import re
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .database import get_db, init_db, utc_now, verify_password

app = FastAPI(title="Route53 Clone API", version="1.0.0")
auth_router = APIRouter(prefix="/api/auth", tags=["Authentication"])
hosted_zones_router = APIRouter(prefix="/api/hosted-zones", tags=["Hosted zones"])
records_router = APIRouter(prefix="/api/hosted-zones", tags=["DNS records"])
allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.environ.get(
        "FRONTEND_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
cookie_secure_value = os.environ.get("SESSION_COOKIE_SECURE", "false").lower()
if cookie_secure_value not in {"true", "false"}:
    raise ValueError("SESSION_COOKIE_SECURE must be 'true' or 'false'.")
cookie_samesite = os.environ.get("SESSION_COOKIE_SAMESITE", "lax").lower()
if cookie_samesite not in {"lax", "strict", "none"}:
    raise ValueError("SESSION_COOKIE_SAMESITE must be 'lax', 'strict', or 'none'.")
cookie_secure = cookie_secure_value == "true"
if cookie_samesite == "none" and not cookie_secure:
    raise ValueError("SESSION_COOKIE_SECURE must be true when SESSION_COOKIE_SAMESITE is 'none'.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ZoneCreateRequest(BaseModel):
    name: str
    comment: str | None = None
    zone_type: str = "public"


class ZoneUpdateRequest(BaseModel):
    name: str | None = None
    comment: str | None = None
    zone_type: str | None = None


class RecordCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1, max_length=10)
    ttl: int = Field(default=300, ge=0, le=2147483647)
    value: str | None = None
    priority: int | None = None
    weight: int | None = None
    port: int | None = None
    target: str | None = None


class RecordUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: str | None = Field(default=None, min_length=1, max_length=10)
    ttl: int | None = Field(default=None, ge=0, le=2147483647)
    value: str | None = None
    priority: int | None = None
    weight: int | None = None
    port: int | None = None
    target: str | None = None


class ImportRequest(BaseModel):
    content: str


class BulkDeleteRequest(BaseModel):
    record_ids: list[int] = Field(..., min_length=1, max_length=100)


def normalize_zone_name(value: str) -> str:
    cleaned = value.strip().rstrip(".")
    if not cleaned:
        raise HTTPException(status_code=422, detail="Hosted zone name is required.")
    try:
        ascii_name = cleaned.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise HTTPException(status_code=422, detail="Hosted zone name is not valid IDNA.") from exc
    if len(ascii_name) > 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in ascii_name.split(".")
    ):
        raise HTTPException(status_code=422, detail="Hosted zone name must be a valid DNS name.")
    if "." not in ascii_name:
        raise HTTPException(status_code=422, detail="Hosted zone name must contain a public domain suffix.")
    return f"{ascii_name}."


def normalize_record_name(value: str, zone_name: str) -> str:
    cleaned = value.strip().lower().rstrip(".")
    if not cleaned or cleaned == "@":
        return zone_name
    if not value.strip().endswith("."):
        cleaned = f"{cleaned}.{zone_name.rstrip('.')}"
    try:
        ascii_name = cleaned.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise HTTPException(status_code=422, detail="Record name is not valid IDNA.") from exc
    labels = ascii_name.split(".")
    if len(ascii_name) > 253 or any(
        not re.fullmatch(r"[a-z0-9_*](?:[a-z0-9_-]{0,61}[a-z0-9_*])?", label)
        or ("*" in label and label != "*")
        for label in labels
    ):
        raise HTTPException(status_code=422, detail="Record name must be a valid DNS name.")
    zone_root = zone_name.rstrip(".")
    if ascii_name != zone_root and not ascii_name.endswith(f".{zone_root}"):
        raise HTTPException(status_code=422, detail="Record name must be within the selected hosted zone.")
    return f"{ascii_name}."


RECORD_TYPES = {"A", "AAAA", "CNAME", "TXT", "MX", "NS", "PTR", "SRV", "CAA"}


def validate_record_data(zone: sqlite3.Row, data: dict[str, Any]) -> dict[str, Any]:
    record_type = str(data.get("type") or "").upper()
    if record_type not in RECORD_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported DNS record type.")
    name = normalize_record_name(str(data.get("name") or ""), zone["name"])
    ttl = data.get("ttl", 300)
    if not isinstance(ttl, int) or not 0 <= ttl <= 2147483647:
        raise HTTPException(status_code=422, detail="TTL must be between 0 and 2147483647 seconds.")
    value = (data.get("value") or "").strip()
    target = (data.get("target") or "").strip().rstrip(".").lower()
    priority, weight, port = data.get("priority"), data.get("weight"), data.get("port")

    def require_target(candidate: str, label: str) -> str:
        if not candidate:
            raise HTTPException(status_code=422, detail=f"{label} is required.")
        try:
            return normalize_zone_name(candidate)
        except HTTPException as exc:
            raise HTTPException(status_code=422, detail=f"{label} must be a valid DNS name.") from exc

    if record_type == "A":
        try:
            value = str(ipaddress.IPv4Address(value))
        except ipaddress.AddressValueError as exc:
            raise HTTPException(status_code=422, detail="A records require a valid IPv4 address.") from exc
    elif record_type == "AAAA":
        try:
            value = str(ipaddress.IPv6Address(value))
        except ipaddress.AddressValueError as exc:
            raise HTTPException(status_code=422, detail="AAAA records require a valid IPv6 address.") from exc
    elif record_type in {"CNAME", "NS", "PTR"}:
        target = require_target(target or value, f"{record_type} target")
        value = target
        if record_type == "CNAME" and name == zone["name"]:
            raise HTTPException(status_code=422, detail="A CNAME record cannot be created at the hosted zone apex.")
    elif record_type == "MX":
        target = require_target(target or value, "MX target")
        if priority is None or not 0 <= priority <= 65535:
            raise HTTPException(status_code=422, detail="MX records require a priority between 0 and 65535.")
        value = target
    elif record_type == "SRV":
        srv_target = target or value
        target = "." if srv_target == "." else require_target(srv_target, "SRV target")
        if priority is None or weight is None or port is None:
            raise HTTPException(status_code=422, detail="SRV records require priority, weight, port, and target.")
        if not 0 <= priority <= 65535 or not 0 <= weight <= 65535 or not 0 <= port <= 65535:
            raise HTTPException(status_code=422, detail="SRV priority, weight, and port must be between 0 and 65535.")
        value = target
    elif record_type == "TXT":
        if not value:
            raise HTTPException(status_code=422, detail="TXT record value is required.")
        if len(value.encode("utf-8")) > 4096:
            raise HTTPException(status_code=422, detail="TXT record value exceeds 4096 bytes.")
    elif record_type == "CAA":
        if not re.fullmatch(
            r"\s*(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\s+[a-z0-9-]{1,15}\s+.+",
            value,
            re.IGNORECASE,
        ):
            raise HTTPException(status_code=422, detail="CAA value must include a supported flag, tag, and value.")
    else:
        if not value:
            raise HTTPException(status_code=422, detail=f"{record_type} record value is required.")

    if record_type == "CNAME" and target.rstrip(".") == name.rstrip("."):
        raise HTTPException(status_code=422, detail="A CNAME record cannot point to itself.")
    return {
        "name": name,
        "type": record_type,
        "ttl": ttl,
        "value": value,
        "priority": priority if record_type in {"MX", "SRV"} else None,
        "weight": weight if record_type == "SRV" else None,
        "port": port if record_type == "SRV" else None,
        "target": target or None if record_type in {"CNAME", "NS", "PTR", "MX", "SRV"} else None,
    }


def ensure_cname_compatibility(
    conn: sqlite3.Connection,
    zone_id: int,
    record: dict[str, Any],
    exclude_id: int | None = None,
) -> None:
    query = "SELECT id, type FROM dns_records WHERE zone_id = ? AND name = ?"
    params: list[Any] = [zone_id, record["name"]]
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    existing_types = {row["type"] for row in conn.execute(query, params).fetchall()}
    if record["type"] == "CNAME" and existing_types:
        raise HTTPException(status_code=422, detail="A CNAME record cannot coexist with other record types at the same name.")
    if "CNAME" in existing_types:
        raise HTTPException(status_code=422, detail="A record cannot coexist with a CNAME record at the same name.")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def ensure_user(conn: sqlite3.Connection, username: str, password: str) -> dict[str, Any] | None:
    user = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if user is None or not verify_password(password, user["password"]):
        return None
    return row_to_dict(user)


def current_user(
    conn: sqlite3.Connection = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias="session_token"),
) -> dict[str, Any]:
    if not session_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    session = conn.execute(
        "SELECT * FROM sessions WHERE token = ?",
        (session_token,),
    ).fetchone()
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return row_to_dict(user)


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "route53-clone"}


@auth_router.post("/login")
def login(request: LoginRequest, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    user = ensure_user(conn, request.username.strip(), request.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = uuid.uuid4().hex
    conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user["id"]))
    conn.commit()
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        max_age=86400,
    )
    return {"user": {"id": user["id"], "username": user["username"], "name": user["name"], "role": user["role"]}}


@auth_router.post("/logout")
def logout(
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias="session_token"),
):
    if session_token:
        conn.execute("DELETE FROM sessions WHERE token = ?", (session_token,))
        conn.commit()
    response.delete_cookie("session_token")
    return {"success": True}


@auth_router.get("/me")
def get_me(user: dict[str, Any] = Depends(current_user)):
    return {"user": {"id": user["id"], "username": user["username"], "name": user["name"], "role": user["role"]}}


def zone_with_records(conn: sqlite3.Connection, zone: sqlite3.Row) -> dict[str, Any]:
    records = conn.execute(
        "SELECT * FROM dns_records WHERE zone_id = ? ORDER BY created_at ASC",
        (zone["id"],),
    ).fetchall()
    return {
        "id": zone["id"],
        "name": zone["name"],
        "comment": zone["comment"],
        "zone_type": zone["zone_type"],
        "created_at": zone["created_at"],
        "updated_at": zone["updated_at"],
        "records": [dict(r) for r in records],
        "record_count": len(records),
    }


@hosted_zones_router.get("")
def list_hosted_zones(
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    offset = (page - 1) * limit
    query = "SELECT * FROM hosted_zones WHERE owner_id = ?"
    params: list[Any] = [user["id"]]
    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")
    count_res = conn.execute(f"SELECT COUNT(*) AS total FROM ({query})", params).fetchone()
    total = count_res["total"] if count_res else 0
    rows = conn.execute(f"{query} ORDER BY created_at DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    zones = [zone_with_records(conn, row) for row in rows]
    return {"items": zones, "page": page, "limit": limit, "total": total}


@hosted_zones_router.post("")
def create_hosted_zone(
    payload: ZoneCreateRequest,
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone_name = normalize_zone_name(payload.name)
    zone_type = payload.zone_type.lower()
    if zone_type not in {"public", "private"}:
        raise HTTPException(status_code=422, detail="Hosted zone type must be public or private.")
    existing = conn.execute("SELECT id FROM hosted_zones WHERE name = ? AND owner_id = ?", (zone_name, user["id"])).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Hosted zone already exists")
    now = utc_now()
    cursor = conn.execute(
        "INSERT INTO hosted_zones (name, comment, zone_type, created_at, updated_at, owner_id) VALUES (?, ?, ?, ?, ?, ?)",
        (zone_name, payload.comment or "", zone_type, now, now, user["id"]),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM hosted_zones WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return zone_with_records(conn, row)


@hosted_zones_router.put("/{zone_id}")
def update_hosted_zone(
    zone_id: int,
    payload: ZoneUpdateRequest,
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone = conn.execute("SELECT * FROM hosted_zones WHERE id = ? AND owner_id = ?", (zone_id, user["id"])).fetchone()
    if zone is None:
        raise HTTPException(status_code=404, detail="Hosted zone not found")
    updates: list[str] = ["updated_at = ?"]
    params: list[Any] = [utc_now()]
    if payload.name is not None:
        new_name = normalize_zone_name(payload.name)
        if new_name != zone["name"]:
            raise HTTPException(status_code=422, detail="Hosted zone names are immutable; create a new hosted zone instead.")
        duplicate = conn.execute(
            "SELECT id FROM hosted_zones WHERE name = ? AND owner_id = ? AND id != ?",
            (new_name, user["id"], zone_id),
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail="Hosted zone already exists.")
        updates.append("name = ?")
        params.append(new_name)
    if payload.comment is not None:
        updates.append("comment = ?")
        params.append(payload.comment)
    if payload.zone_type is not None:
        zone_type = payload.zone_type.lower()
        if zone_type not in {"public", "private"}:
            raise HTTPException(status_code=422, detail="Hosted zone type must be public or private.")
        updates.append("zone_type = ?")
        params.append(zone_type)
    conn.execute(f"UPDATE hosted_zones SET {', '.join(updates)} WHERE id = ? AND owner_id = ?", [*params, zone_id, user["id"]])
    conn.commit()
    row = conn.execute("SELECT * FROM hosted_zones WHERE id = ?", (zone_id,)).fetchone()
    return zone_with_records(conn, row)


@hosted_zones_router.get("/{zone_id}")
def get_hosted_zone(
    zone_id: int,
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone = zone_guard(zone_id, user["id"], conn)
    return zone_with_records(conn, zone)


@hosted_zones_router.delete("/{zone_id}")
def delete_hosted_zone(
    zone_id: int,
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone = conn.execute("SELECT * FROM hosted_zones WHERE id = ? AND owner_id = ?", (zone_id, user["id"])).fetchone()
    if zone is None:
        raise HTTPException(status_code=404, detail="Hosted zone not found")
    conn.execute("DELETE FROM hosted_zones WHERE id = ? AND owner_id = ?", (zone_id, user["id"]))
    conn.commit()
    return {"success": True}


def zone_guard(zone_id: int, user_id: int, conn: sqlite3.Connection):
    zone = conn.execute("SELECT * FROM hosted_zones WHERE id = ? AND owner_id = ?", (zone_id, user_id)).fetchone()
    if zone is None:
        raise HTTPException(status_code=404, detail="Hosted zone not found")
    return zone


@records_router.get("/{zone_id}/records")
def list_records(
    zone_id: int,
    search: str | None = None,
    record_type: str | None = Query(default=None, alias="type"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone = zone_guard(zone_id, user["id"], conn)
    query = "SELECT * FROM dns_records WHERE zone_id = ?"
    params: list[Any] = [zone_id]
    if search:
        query += " AND (name LIKE ? OR type LIKE ? OR value LIKE ? OR target LIKE ?)"
        needle = f"%{search}%"
        params.extend([needle, needle, needle, needle])
    if record_type:
        query += " AND type = ?"
        params.append(record_type.upper())
    total = conn.execute(f"SELECT COUNT(*) AS total FROM ({query})", params).fetchone()["total"]
    query += " ORDER BY created_at ASC"
    rows = conn.execute(f"{query} LIMIT ? OFFSET ?", [*params, limit, (page - 1) * limit]).fetchall()
    return {
        "items": [dict(r) for r in rows],
        "zone": {"id": zone["id"], "name": zone["name"]},
        "page": page,
        "limit": limit,
        "total": total,
    }


@records_router.post("/{zone_id}/records")
def create_record(
    zone_id: int,
    payload: RecordCreateRequest,
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone = zone_guard(zone_id, user["id"], conn)
    record = validate_record_data(zone, payload.model_dump())
    ensure_cname_compatibility(conn, zone_id, record)
    now = utc_now()
    cursor = conn.execute(
        "INSERT INTO dns_records (zone_id, name, type, ttl, value, priority, weight, port, target, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            zone_id, record["name"], record["type"], record["ttl"], record["value"],
            record["priority"], record["weight"], record["port"], record["target"], now, now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM dns_records WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


@records_router.put("/{zone_id}/records/{record_id}")
def update_record(
    zone_id: int,
    record_id: int,
    payload: RecordUpdateRequest,
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone = zone_guard(zone_id, user["id"], conn)
    row = conn.execute("SELECT * FROM dns_records WHERE id = ? AND zone_id = ?", (record_id, zone_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="DNS record not found")
    record = validate_record_data(
        zone,
        {
            "name": payload.name if payload.name is not None else row["name"],
            "type": payload.type if payload.type is not None else row["type"],
            "ttl": payload.ttl if payload.ttl is not None else row["ttl"],
            "value": payload.value if payload.value is not None else row["value"],
            "priority": payload.priority if payload.priority is not None else row["priority"],
            "weight": payload.weight if payload.weight is not None else row["weight"],
            "port": payload.port if payload.port is not None else row["port"],
            "target": (
                payload.target
                if payload.target is not None
                else payload.value if payload.value is not None else row["target"]
            ),
        },
    )
    ensure_cname_compatibility(conn, zone_id, record, record_id)
    updates: list[str] = ["updated_at = ?"]
    params: list[Any] = [utc_now()]
    for field in ("name", "type", "ttl", "value", "priority", "weight", "port", "target"):
        updates.append(f"{field} = ?")
        params.append(record[field])
    conn.execute(f"UPDATE dns_records SET {', '.join(updates)} WHERE id = ? AND zone_id = ?", [*params, record_id, zone_id])
    conn.commit()
    updated = conn.execute("SELECT * FROM dns_records WHERE id = ?", (record_id,)).fetchone()
    return dict(updated)


@records_router.delete("/{zone_id}/records/{record_id}")
def delete_record(
    zone_id: int,
    record_id: int,
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone_guard(zone_id, user["id"], conn)
    deleted = conn.execute("DELETE FROM dns_records WHERE id = ? AND zone_id = ?", (record_id, zone_id))
    conn.commit()
    if deleted.rowcount == 0:
        raise HTTPException(status_code=404, detail="DNS record not found")
    return {"success": True}


@records_router.post("/{zone_id}/records/bulk-delete")
def bulk_delete_records(
    zone_id: int,
    payload: BulkDeleteRequest,
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone_guard(zone_id, user["id"], conn)
    record_ids = sorted(set(payload.record_ids))
    placeholders = ",".join("?" for _ in record_ids)
    found = conn.execute(
        f"SELECT id FROM dns_records WHERE zone_id = ? AND id IN ({placeholders})",
        [zone_id, *record_ids],
    ).fetchall()
    if len(found) != len(record_ids):
        raise HTTPException(status_code=404, detail="One or more selected records were not found in this hosted zone.")
    conn.execute(
        f"DELETE FROM dns_records WHERE zone_id = ? AND id IN ({placeholders})",
        [zone_id, *record_ids],
    )
    conn.commit()
    return {"success": True, "deleted": len(record_ids)}


def parse_bind_zone(content: str, zone_name: str) -> list[dict[str, Any]]:
    import shlex

    records: list[dict[str, Any]] = []
    current_origin = zone_name.rstrip(".")
    default_ttl = 300
    previous_owner = "@"
    supported_types = RECORD_TYPES
    logical_lines: list[tuple[str, bool]] = []
    pending = ""
    pending_indented = False
    depth = 0
    for raw_line in content.splitlines():
        if not raw_line.strip():
            continue
        if not pending:
            pending_indented = raw_line[0].isspace()
        pending = f"{pending} {raw_line.strip()}".strip()
        depth += raw_line.count("(") - raw_line.count(")")
        if depth > 0:
            continue
        logical_lines.append((pending.replace("(", " ").replace(")", " ").strip(), pending_indented))
        pending = ""
    if pending:
        raise HTTPException(status_code=422, detail="BIND input contains an unclosed parenthesized record.")

    for line, owner_omitted in logical_lines:
        if line.startswith("$ORIGIN"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                current_origin = parts[1].rstrip(".").lower()
            continue
        if line.startswith("$TTL"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2 and parts[1].isdigit():
                default_ttl = int(parts[1])
            continue
        if "(" in line or ")" in line:
            line = line.replace("(", " ").replace(")", " ").strip()
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid BIND quoting: {exc}") from exc
        if not tokens:
            continue
        if owner_omitted:
            owner = previous_owner
            fields = tokens
        else:
            owner = tokens[0].lower()
            previous_owner = owner
            fields = tokens[1:]
        ttl = default_ttl
        record_type = None
        values: list[str] = []
        for index, token in enumerate(fields):
            upper = token.upper()
            if upper in supported_types or upper in {"SOA", "DNSKEY", "DS", "RRSIG", "NSEC", "NSEC3"}:
                record_type = upper
                values = fields[index + 1 :]
                break
            if token.isdigit():
                ttl = int(token)
        if record_type is None or record_type not in supported_types:
            continue
        if owner == "@":
            name = f"{current_origin}."
        elif owner.endswith("."):
            name = owner
        else:
            name = f"{owner}.{current_origin}."
        data: dict[str, Any] = {
            "name": name,
            "type": record_type,
            "ttl": ttl,
            "value": " ".join(values),
            "priority": None,
            "weight": None,
            "port": None,
            "target": None,
        }
        if record_type == "MX" and len(values) >= 2:
            try:
                data["priority"] = int(values[0])
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="BIND MX priority must be an integer.") from exc
            data["value"] = values[1]
            data["target"] = values[1]
        elif record_type == "SRV" and len(values) >= 4:
            try:
                data["priority"], data["weight"], data["port"] = map(int, values[:3])
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="BIND SRV priority, weight, and port must be integers.") from exc
            data["value"] = values[3]
            data["target"] = values[3]
        elif record_type in {"CNAME", "NS", "PTR"} and values:
            data["value"] = values[0]
            data["target"] = values[0]
        records.append(data)
    return records


@records_router.post("/{zone_id}/import")
def import_zone_records(
    zone_id: int,
    payload: ImportRequest,
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone = zone_guard(zone_id, user["id"], conn)
    parsed = parse_bind_zone(payload.content, zone["name"])
    created_count = 0
    for item in parsed:
        record = validate_record_data(zone, item)
        ensure_cname_compatibility(conn, zone_id, record)
        conn.execute(
            "INSERT INTO dns_records (zone_id, name, type, ttl, value, priority, weight, port, target, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                zone_id, record["name"], record["type"], record["ttl"], record["value"],
                record["priority"], record["weight"], record["port"], record["target"], utc_now(), utc_now(),
            ),
        )
        created_count += 1
    conn.commit()
    return {"success": True, "created": created_count, "zone": zone["name"]}


@records_router.get("/{zone_id}/export")
def export_zone_records(
    zone_id: int,
    fmt: str = "json",
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    zone = zone_guard(zone_id, user["id"], conn)
    rows = conn.execute("SELECT * FROM dns_records WHERE zone_id = ? ORDER BY created_at ASC", (zone_id,)).fetchall()
    records = [dict(r) for r in rows]
    if fmt.lower() not in {"json", "bind"}:
        raise HTTPException(status_code=422, detail="Export format must be 'json' or 'bind'.")
    if fmt.lower() == "bind":
        lines = [f"$ORIGIN {zone['name']}"]
        for record in records:
            name = record["name"]
            if record["name"] == zone["name"].rstrip("."):
                name = "@"
            if record["type"] == "A":
                lines.append(f"{name} {record['ttl']} IN A {record['value']}")
            elif record["type"] == "AAAA":
                lines.append(f"{name} {record['ttl']} IN AAAA {record['value']}")
            elif record["type"] == "CNAME":
                lines.append(f"{name} {record['ttl']} IN CNAME {record['value']}")
            elif record["type"] == "TXT":
                escaped_value = str(record["value"]).replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{name} {record["ttl"]} IN TXT "{escaped_value}"')
            elif record["type"] == "MX":
                lines.append(f"{name} {record['ttl']} IN MX {record['priority']} {record['value']}")
            elif record["type"] == "NS":
                lines.append(f"{name} {record['ttl']} IN NS {record['value']}")
            elif record["type"] == "PTR":
                lines.append(f"{name} {record['ttl']} IN PTR {record['value']}")
            elif record["type"] == "SRV":
                lines.append(f"{name} {record['ttl']} IN SRV {record['priority']} {record['weight']} {record['port']} {record['value']}")
            elif record["type"] == "CAA":
                lines.append(f"{name} {record['ttl']} IN CAA {record['value']}")
        return PlainTextResponse("\n".join(lines))
    return JSONResponse({"zone": zone["name"], "records": records})


@app.get("/")
def root():
    return {"message": "Route53 Clone API is running"}


app.include_router(auth_router)
app.include_router(hosted_zones_router)
app.include_router(records_router)
