from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "effectcraft-accounts.sqlite3"
JWT_SECRET = os.environ.get("JWT_SECRET", "")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
TOKEN_TTL_DAYS = 30
ADMIN_TOKEN_TTL_HOURS = 8
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
app = FastAPI(title="EffectCraft Home Account Server", version="1.0.0")
rate_lock = __import__("threading").Lock()
rate_buckets: dict[str, list[float]] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


@app.on_event("startup")
def startup() -> None:
    if len(JWT_SECRET) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters. Run setup.ps1 first.")
    if len(ADMIN_PASSWORD) < 12 or ADMIN_PASSWORD.lower() in {"changeme", "password123456"}:
        raise RuntimeError("Set a unique ADMIN_PASSWORD of at least 12 characters in account-server/.env.")
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                qq TEXT NOT NULL UNIQUE,
                wechat TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                avatar_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                banned_until TEXT,
                ban_reason TEXT NOT NULL DEFAULT ''
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_accounts_name ON accounts(name)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_accounts_created ON accounts(created_at)")


def rate_limit(request: Request, bucket: str, limit: int = 8) -> None:
    ip = request.client.host if request.client else "unknown"
    key = f"{bucket}:{ip}"
    now = time.monotonic()
    with rate_lock:
        recent = [t for t in rate_buckets.get(key, []) if now - t < 60]
        if len(recent) >= limit:
            raise HTTPException(429, "操作过于频繁，请一分钟后再试")
        recent.append(now)
        rate_buckets[key] = recent


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_token(subject: str, role: str, ttl: timedelta) -> str:
    now = int(time.time())
    header = b64url(b'{"alg":"HS256","typ":"JWT"}')
    payload = b64url(json.dumps({"sub": subject, "role": role, "iat": now, "exp": now + int(ttl.total_seconds())}, separators=(",", ":")).encode())
    signing = f"{header}.{payload}".encode("ascii")
    signature = b64url(hmac.new(JWT_SECRET.encode(), signing, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def decode_token(token: str) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".")
        signing = f"{header}.{payload}".encode("ascii")
        expected = b64url(hmac.new(JWT_SECRET.encode(), signing, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
        if int(claims["exp"]) <= int(time.time()):
            raise ValueError("expired")
        if claims.get("role") not in {"user", "admin"}:
            raise ValueError("role")
        return claims
    except Exception as exc:
        raise HTTPException(401, "登录已失效，请重新登录") from exc


def bearer_claims(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "需要登录")
    return decode_token(authorization[7:].strip())


def current_user(claims: dict[str, Any] = Depends(bearer_claims)) -> sqlite3.Row:
    if claims["role"] != "user":
        raise HTTPException(403, "账号权限不足")
    with db() as con:
        row = con.execute("SELECT * FROM accounts WHERE id=?", (claims["sub"],)).fetchone()
    if row is None:
        raise HTTPException(401, "账号不存在")
    enforce_unbanned(row)
    return row


def current_admin(claims: dict[str, Any] = Depends(bearer_claims)) -> dict[str, Any]:
    if claims["role"] != "admin" or claims["sub"] != ADMIN_USERNAME:
        raise HTTPException(403, "仅管理员可以执行此操作")
    return claims


def enforce_unbanned(row: sqlite3.Row) -> None:
    until = row["banned_until"]
    if until:
        try:
            expires = parse_iso(until)
            if expires > utcnow():
                raise HTTPException(423, {
                    "code": "banned",
                    "until": until,
                    "reason": row["ban_reason"] or "未填写封禁原因",
                })
        except HTTPException:
            raise
        except Exception:
            # An invalid ban timestamp is treated as blocked, never silently ignored.
            raise HTTPException(423, {"code": "banned", "until": until, "reason": row["ban_reason"] or "封禁状态异常，请联系管理员"})
        with db() as con:
            con.execute("UPDATE accounts SET banned_until=NULL, ban_reason='' WHERE id=?", (row["id"],))


def public_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "qq": row["qq"],
        "wechat": row["wechat"],
        "name": row["name"],
        "avatar_url": row["avatar_url"],
        "created_at": row["created_at"],
        "banned_until": row["banned_until"],
        "ban_reason": row["ban_reason"],
    }


class RegisterBody(BaseModel):
    qq: str = Field(min_length=5, max_length=12)
    wechat: str = Field(min_length=6, max_length=32)
    name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=8, max_length=128)
    avatar_url: str = Field(default="", max_length=512)


class LoginBody(BaseModel):
    identifier: str = Field(min_length=5, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ProfileBody(BaseModel):
    qq: str = Field(min_length=5, max_length=12)
    wechat: str = Field(min_length=6, max_length=32)
    name: str = Field(min_length=1, max_length=40)
    avatar_url: str = Field(default="", max_length=512)
    current_password: str = Field(default="", max_length=128)
    new_password: str = Field(default="", max_length=128)


class AdminLoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class BanBody(BaseModel):
    banned_until: str | None
    reason: str = Field(default="", max_length=500)


def validate_profile(qq: str, wechat: str, name: str, avatar_url: str) -> tuple[str, str, str, str]:
    qq = qq.strip()
    wechat = wechat.strip()
    name = name.strip()
    avatar_url = avatar_url.strip()
    if not re.fullmatch(r"[1-9][0-9]{4,11}", qq):
        raise HTTPException(422, "QQ号应填写5至12位数字")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{5,31}", wechat):
        raise HTTPException(422, "微信号应以字母开头，使用6至32位字母、数字、下划线或短横线")
    if not name:
        raise HTTPException(422, "姓名不能为空")
    if avatar_url and not avatar_url.startswith(("https://", "http://")):
        raise HTTPException(422, "头像地址必须以 http:// 或 https:// 开头")
    return qq, wechat.lower(), name, avatar_url


def account_by_id(user_id: str) -> sqlite3.Row:
    with db() as con:
        row = con.execute("SELECT * FROM accounts WHERE id=?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "账号不存在")
    return row


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "EffectCraft Home Account Server", "time": iso(utcnow())}


@app.post("/v1/register")
def register(body: RegisterBody, request: Request) -> dict[str, Any]:
    rate_limit(request, "register", 5)
    qq, wechat, name, avatar_url = validate_profile(body.qq, body.wechat, body.name, body.avatar_url)
    user_id = str(uuid.uuid4())
    created_at = iso(utcnow())
    hashed = password_hasher.hash(body.password)
    try:
        with db() as con:
            con.execute(
                "INSERT INTO accounts(id,qq,wechat,name,password_hash,avatar_url,created_at) VALUES(?,?,?,?,?,?,?)",
                (user_id, qq, wechat, name, hashed, avatar_url, created_at),
            )
            row = con.execute("SELECT * FROM accounts WHERE id=?", (user_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "QQ号或微信号已被注册") from exc
    return {"token": make_token(user_id, "user", timedelta(days=TOKEN_TTL_DAYS)), "user": public_user(row)}


@app.post("/v1/login")
def login(body: LoginBody, request: Request) -> dict[str, Any]:
    rate_limit(request, "login", 8)
    identifier = body.identifier.strip()
    with db() as con:
        row = con.execute("SELECT * FROM accounts WHERE qq=? OR wechat=?", (identifier, identifier.lower())).fetchone()
    if row is None:
        raise HTTPException(401, "QQ号/微信号或密码错误")
    try:
        password_hasher.verify(row["password_hash"], body.password)
    except (VerifyMismatchError, VerificationError):
        raise HTTPException(401, "QQ号/微信号或密码错误")
    if password_hasher.check_needs_rehash(row["password_hash"]):
        with db() as con:
            con.execute("UPDATE accounts SET password_hash=? WHERE id=?", (password_hasher.hash(body.password), row["id"]))
    enforce_unbanned(row)
    row = account_by_id(row["id"])
    return {"token": make_token(row["id"], "user", timedelta(days=TOKEN_TTL_DAYS)), "user": public_user(row)}


@app.get("/v1/me")
def me(row: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    return {"user": public_user(row)}


@app.post("/v1/profile")
def update_profile(body: ProfileBody, row: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    qq, wechat, name, avatar_url = validate_profile(body.qq, body.wechat, body.name, body.avatar_url)
    new_hash = row["password_hash"]
    if body.new_password:
        if len(body.new_password) < 8:
            raise HTTPException(422, "新密码至少8位")
        try:
            password_hasher.verify(row["password_hash"], body.current_password)
        except (VerifyMismatchError, VerificationError):
            raise HTTPException(401, "当前密码不正确")
        new_hash = password_hasher.hash(body.new_password)
    try:
        with db() as con:
            con.execute(
                "UPDATE accounts SET qq=?,wechat=?,name=?,avatar_url=?,password_hash=? WHERE id=?",
                (qq, wechat, name, avatar_url, new_hash, row["id"]),
            )
            updated = con.execute("SELECT * FROM accounts WHERE id=?", (row["id"],)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "QQ号或微信号已被其他账号使用") from exc
    return {"user": public_user(updated)}


@app.post("/v1/admin/login")
def admin_login(body: AdminLoginBody, request: Request) -> dict[str, Any]:
    rate_limit(request, "admin-login", 5)
    if not (secrets.compare_digest(body.username, ADMIN_USERNAME) and secrets.compare_digest(body.password, ADMIN_PASSWORD)):
        raise HTTPException(401, "管理员账号或密码错误")
    token = make_token(ADMIN_USERNAME, "admin", timedelta(hours=ADMIN_TOKEN_TTL_HOURS))
    return {"token": token, "expires_in": ADMIN_TOKEN_TTL_HOURS * 3600}


@app.get("/v1/admin/users")
def admin_users(q: str = "", _: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
    query = q.strip()
    with db() as con:
        if query:
            like = f"%{query}%"
            rows = con.execute(
                "SELECT * FROM accounts WHERE qq LIKE ? OR wechat LIKE ? OR name LIKE ? ORDER BY created_at DESC LIMIT 500",
                (like, like, like),
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM accounts ORDER BY created_at DESC LIMIT 500").fetchall()
    return {"users": [public_user(row) for row in rows]}


@app.post("/v1/admin/users/{user_id}/ban")
def admin_ban(user_id: str, body: BanBody, _: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
    account_by_id(user_id)
    if body.banned_until is None:
        with db() as con:
            con.execute("UPDATE accounts SET banned_until=NULL, ban_reason='' WHERE id=?", (user_id,))
    else:
        try:
            until = parse_iso(body.banned_until)
        except Exception as exc:
            raise HTTPException(422, "封禁时间格式不正确") from exc
        if until <= utcnow():
            raise HTTPException(422, "封禁时间必须晚于当前时间")
        reason = body.reason.strip()
        if not reason:
            raise HTTPException(422, "请填写封禁原因")
        with db() as con:
            con.execute(
                "UPDATE accounts SET banned_until=?, ban_reason=? WHERE id=?",
                (iso(until), reason, user_id),
            )
    return {"user": public_user(account_by_id(user_id))}


@app.get("/v1/admin/users/{user_id}")
def admin_user(user_id: str, _: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
    return {"user": public_user(account_by_id(user_id))}
