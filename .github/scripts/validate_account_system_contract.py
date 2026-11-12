#!/usr/bin/env python3
"""Static contract checks for EffectCraft's account, ban, P2P and admin-node flow."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit(f"FAIL: required account-system source missing: {relative}")
    return path.read_text(encoding="utf-8")


checks: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "SQLite account schema supports QQ/WeChat alternatives and ban fields",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/LanAccountServer.java",
        (
            "CREATE TABLE accounts",
            "qq TEXT UNIQUE",
            "wechat TEXT UNIQUE",
            "banned_until TEXT",
            "ban_reason TEXT",
        ),
    ),
    (
        "Register and login return both a token and user profile",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/LanAccountServer.java",
        (
            'path.equals("/v1/register")',
            'path.equals("/v1/login")',
            'out.put("token"',
            'out.put("user", findUser(id))',
        ),
    ),
    (
        "Ban state is checked at login, profile update, and periodic /me verification",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/LanAccountServer.java",
        (
            'if (isBanned(user)) return error(423',
            'if (isBanned(current)) return error(423',
            "private boolean isBanned(JSONObject user)",
            'until.isAfter(Instant.now())',
            'path.equals("/v1/me")',
        ),
    ),
    (
        "Administrator ban and unban are protected by admin authorization",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/LanAccountServer.java",
        (
            'authorize(headers, "admin")',
            'tail.endsWith("/ban")',
            'values.putNull("banned_until")',
            'values.put("ban_reason", "")',
            '请填写封禁原因',
        ),
    ),
    (
        "P2P account channel pins the administrator peer before credentials are sent",
        "p2p-bridge/src/lib.rs",
        (
            '/effectcraft/account-api/1.0.0',
            'preferred_peer_id',
            'peer_is_pinned',
            'dispatch_deferred_for_peer',
            'forward_to_local_account_service',
            'ACCOUNT_RPC_PROTOCOL',
            'ADMIN_ACCOUNT_BRIDGE',
        ),
    ),
    (
        "Client retries a closed P2P command channel while preserving the pinned peer",
        "p2p-bridge/src/lib.rs",
        (
            'fn ensure_client_rpc_sender()',
            'fn send_account_rpc(',
            'clear_rpc_command_tx();',
            'P2P 网络节点自动恢复',
            'account_rpc_request_keeps_the_pinned_admin_identity',
        ),
    ),
    (
        "Admin phone has a real on/off switch and stops the native P2P node",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/MainActivity.java",
        (
            'node_server_enabled',
            '账号服务器开关',
            'startNodeServerService()',
            'stopService(new Intent(this, LanServerService.class))',
        ),
    ),
    (
        "Admin service stops account bridge and native P2P on shutdown",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/LanServerService.java",
        (
            'P2PAccountBridge.stop();',
            'NativeP2P.stop();',
            'accountServer.stopServer();',
        ),
    ),
    (
        "Android account photo picker is image-only and compresses local avatars",
        ".github/scripts/add_account_avatar_picker.py",
        (
            'image/*',
            'rfd::artcraft_saf::pick_image()',
            '256',
            'data:image/jpeg;base64,',
            'AvatarTarget::Register',
            'AvatarTarget::Profile',
        ),
    ),
    (
        "Account page requests register/login/me/profile through the P2P proxy",
        ".github/scripts/add_home_lan_account_gate.py",
        (
            '"/v1/register"',
            '"/v1/login"',
            '"/v1/me"',
            '"/v1/profile"',
            '"preferred_peer_id": preferred_peer_id',
            '127.0.0.1:8789',
        ),
    ),
]


for label, relative, needles in checks:
    source = read(relative)
    missing = [needle for needle in needles if needle not in source]
    if missing:
        raise SystemExit(f"FAIL: {label}\n  file: {relative}\n  missing: {missing}")
    print(f"PASS: {label}")

print(f"PASS: all {len(checks)} account-system contracts are present")
