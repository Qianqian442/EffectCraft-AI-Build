"""End-to-end smoke test for registration, login, admin search and ban enforcement."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("ACCOUNT_SERVER_URL", "http://127.0.0.1:8787")
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


def call(method: str, path: str, body: dict | None = None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> None:
    for _ in range(40):
        try:
            status, _ = call("GET", "/health")
            if status == 200:
                break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("Account server did not become ready")

    suffix = uuid.uuid4().hex[:6]
    qq = "8" + str(int(suffix, 16) % 10000000).zfill(7)
    wechat = "ecuser" + suffix
    password = "SmokeTest-" + uuid.uuid4().hex
    status, registered = call("POST", "/v1/register", {
        "qq": qq, "wechat": wechat, "name": "CI Smoke Test",
        "password": password, "avatar_url": ""
    })
    assert status == 200, (status, registered)
    user_token = registered["token"]
    user_id = registered["user"]["id"]
    assert "password" not in registered["user"] and "password_hash" not in registered["user"]

    status, current = call("GET", "/v1/me", token=user_token)
    assert status == 200 and current["user"]["id"] == user_id

    status, login = call("POST", "/v1/login", {"identifier": qq, "password": password})
    assert status == 200 and login["user"]["id"] == user_id

    status, admin = call("POST", "/v1/admin/login", {"username": "admin", "password": ADMIN_PASSWORD})
    assert status == 200, (status, admin)
    admin_token = admin["token"]

    status, listing = call("GET", "/v1/admin/users?q=" + qq, token=admin_token)
    assert status == 200 and any(item["id"] == user_id for item in listing["users"])

    banned_until = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    status, banned = call("POST", f"/v1/admin/users/{user_id}/ban", {
        "banned_until": banned_until, "reason": "CI 封禁测试原因"
    }, admin_token)
    assert status == 200 and banned["user"]["ban_reason"] == "CI 封禁测试原因"

    status, rejected = call("GET", "/v1/me", token=user_token)
    assert status == 423 and rejected["detail"]["reason"] == "CI 封禁测试原因"

    status, unbanned = call("POST", f"/v1/admin/users/{user_id}/ban", {
        "banned_until": None, "reason": ""
    }, admin_token)
    assert status == 200 and unbanned["user"]["banned_until"] is None

    status, current = call("GET", "/v1/me", token=user_token)
    assert status == 200 and current["user"]["id"] == user_id
    print("PASS: register, password login, admin search, timed ban, ban reason and unban.")


if __name__ == "__main__":
    main()
