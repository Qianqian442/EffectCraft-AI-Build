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
        "Ban state is checked at login, profile update, and explicit session validation",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/LanAccountServer.java",
        (
            'if (isBanned(user)) return error(423',
            'if (isBanned(current)) return error(423',
            "private boolean isBanned(JSONObject user)",
            'Instant.parse(until).isAfter(Instant.now())',
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
        "Main APK verifies a saved session at startup and on explicit retry",
        ".github/scripts/add_home_lan_account_gate.py",
        (
            "if self.token.is_some()",
            'self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);',
            "fn retry(",
        ),
    ),
    (
        "Admin APK explicitly signs with the persisted keystore path",
        "admin-app/app/build.gradle",
        (
            'System.getProperty("user.home") + "/.android/debug.keystore"',
            'signingConfig signingConfigs.debug',
            'keyAlias "androiddebugkey"',
        ),
    ),
    (
        "Android SQLite account lifecycle regression tests are part of the admin build",
        "admin-app/app/src/test/java/com/qianqian/effectcraftadmin/LanAccountServerAccountFlowTest.java",
        (
            'qqRegistrationLoginBanAndUnbanUseTheSameSqliteAuthority',
            'p2pLoopbackBridgeForwardsARegistrationIntoSqlite',
            'wechatOnlyRegistrationAndLoginAreSupported',
            'banned user must not log in',
            'banned users cannot update profile',
            'unbanned account can log in again',
            'PHOTO_AVATAR',
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
            'getSharedPreferences(LanServerService.SETTINGS_PREFS, MODE_PRIVATE)',
        ),
    ),
    (
        "Admin service stops account bridge and native P2P on shutdown",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/LanServerService.java",
        (
            'P2PAccountBridge.stop();',
            'NativeP2P.stop();',
            'accountServer.stopServer();',
            'getSharedPreferences(SETTINGS_PREFS, MODE_PRIVATE)',
            'START_NOT_STICKY',
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
            'rfd = { path = "../../vendor/rfd", default-features = false }',
            'pollster = "0.4"',
            'reader.limits(limits);',
        ),
    ),
    (
        "Client blocks the editor on a ban response or unavailable admin authority",
        ".github/scripts/add_home_lan_account_gate.py",
        (
            "response.status == 423",
            "self.mode = Mode::Banned",
            "Mode::Unavailable => centered_window",
            "Mode::Banned => centered_window",
            "为防止离线绕过封禁，软件暂时保持锁定",
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
    (
        "Cloudflare account service is controlled by an admin-only D1-backed global switch",
        "cloudflare-worker/src/index.js",
        (
            "account_service_settings",
            "requireAccountServiceEnabled",
            "/v1/admin/account-service",
            "account_service_disabled",
            'url.pathname.startsWith("/v1/") && !url.pathname.startsWith("/v1/admin/")',
            "adminSetAccountServiceState",
        ),
    ),
    (
        "Global Cloudflare service changes are pushed over existing online node WebSockets",
        "cloudflare-worker/src/node_network_hub.js",
        (
            "/account-service-state",
            "account_service_state",
            "account_service_enabled",
            "socket.send(payload)",
            'socket.close(4002, "global account service disabled")',
        ),
    ),

    (
        "Cloudflare admin APK toggle controls all users and preserves admin recovery access",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/MainActivity.java",
        (
            "/v1/admin/account-service",
            "云端账号服务器开关（全体用户）",
            "所有用户的注册、登录和账号验证均已暂停",
            "管理员仍可登录本管理版并重新开启",
            "if (isCloudflareMode())",
        ),
    ),
    (
        "Cloudflare server enforces QQ/WeChat whitelist on registration, login and session/profile access",
        "cloudflare-worker/src/index.js",
        (
            "account_whitelist",
            "requireWhitelistedIdentifiers(env.DB, body.qq, body.wechat)",
            "isWhitelistAllowed(env.DB, identifierKind, identifier)",
            "adminAddWhitelist",
            "adminRemoveWhitelist",
            "/v1/whitelist",
            "qq_hashes",
            "wechat_hashes",
            "not_whitelisted",
        ),
    ),
    (
        "Admin APK can add, list and remove QQ/WeChat whitelist entries",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/MainActivity.java",
        (
            "addWhitelistPanel(page)",
            "/v1/admin/whitelist",
            "/v1/admin/whitelist/remove",
            "加入白名单",
            "移除白名单",
        ),
    ),
    (
        "Main APK downloads a hashed whitelist locally and prechecks account identifiers",
        ".github/scripts/add_account_whitelist_local_cache.py",
        (
            "EFFECTCRAFT_LOCAL_WHITELIST_AND_OFFLINE_BAN_V1",
            "identifier_digest",
            "self.whitelist_has",
            "effectcraft-account-whitelist.json",
            "/v1/whitelist",
        ),
    ),
    (
        "Main APK stores ban/whitelist data locally but hides security details from the ordinary UI",
        ".github/scripts/hide_account_security_details.py",
        (
            "effectcraft-account-ban.json",
            "effectcraft-account-whitelist.json",
            "EFFECTCRAFT_ACCOUNT_SECURITY_DETAIL_DISPLAY_SUPPRESSED_V1",
            "账号当前无法通过验证",
            "self.status = if response.status == 403 || response.status == 423",
        ),
    ),
    (
        "Main APK receives global service state pushes without adding HTTP polling",
        ".github/scripts/convert_account_gate_to_cloud.py",
        (
            "event_sender: Option<mpsc::Sender<Result<Value, String>>>",
            "account_service_state",
            "service_disabled",
            "请等待管理员重新开启服务器，再关闭并重新打开 Ae",
            'if app.account.status.contains("云端账号服务器已由管理员关闭")',
            'ctx.send_viewport_cmd(egui::ViewportCommand::Close)',
            "app.account.poll_events(config)",
        ),
    )
]


for label, relative, needles in checks:
    source = read(relative)
    missing = [needle for needle in needles if needle not in source]
    if missing:
        raise SystemExit(f"FAIL: {label}\n  file: {relative}\n  missing: {missing}")
    print(f"PASS: {label}")

gate_source = read(".github/scripts/add_home_lan_account_gate.py")
if "Duration::from_secs(10)" in gate_source or "last_verified" in gate_source:
    raise SystemExit("FAIL: timed ten-second account verification must not be present")
print("PASS: no fixed ten-second account verification polling")
print(f"PASS: all {len(checks)} account-system contracts are present")
