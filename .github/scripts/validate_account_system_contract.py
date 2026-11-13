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
        "Ban state is checked at login, profile update, and explicit /v1/me requests",
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
        "Main APK receives administrator ban/unban events without periodic account polling",
        ".github/scripts/add_home_lan_account_gate.py",
        (
            "start_account_event_listener",
            "ACCOUNT_EVENT_PROXY",
            "fn poll_events(&mut self)",
            'self.mode = Mode::Banned',
            'self.mode = Mode::Editor',
            '"/v1/me"',
        ),
    ),
    (
        "P2P routes account status pushes only from the pinned administrator identity",
        "p2p-bridge/src/lib.rs",
        (
            "NotifyAccountStatus",
            '"/v1/events/push"',
            "connected_accounts",
            "pinned_admin_peer.as_ref() == Some(&peer)",
            "forward_to_local_client_event",
            "CLIENT_EVENT_PROXY",
        ),
    ),
    (
        "Administrator sends ban and unban changes to logged-in P2P devices",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/LanAccountServer.java",
        (
            "NativeP2P.notifyAccountStatus",
            'nowBanned ? "banned" : "unbanned"',
            "Push to every authenticated P2P client",
        ),
    ),
    (
        "Admin APK exposes the native account-status push command",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/NativeP2P.java",
        (
            "nativeNotifyAccountStatus",
            "static void notifyAccountStatus",
            "Account status push was not queued",
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
            '本机 P2P 辅助节点开关',
            'startNodeServerService()',
            'stopService(new Intent(this, LanServerService.class))',
            'getSharedPreferences(LanServerService.SETTINGS_PREFS, MODE_PRIVATE)',
        ),
    ),
    (
        "Admin shows the exact cloud account total and can switch the shared cloud account service",
        "admin-app/app/src/main/java/com/qianqian/effectcraftadmin/MainActivity.java",
        (
            'total_count',
            '云端已注册账号：',
            '当前显示 ',
            'addAccountServiceControl(page)',
            'GET", "/v1/admin/server"',
            'POST", "/v1/admin/server"',
            'setAccountServiceEnabled',
            'new ScrollView(this)',
            'card.setOrientation(LinearLayout.HORIZONTAL)',
            'avatarView.setOnClickListener(v -> showUserDetails(user))',
            'actions.setOrientation(LinearLayout.VERTICAL)',
            'private void askPermanentBanReason(String id)',
            'submitBan(id, "permanent", why)',
        ),
    ),
    (
        "Cloud account API keeps administrator controls available while the user account service can be switched off",
        "cloudflare-worker/src/index.js",
        (
            'account_service_state',
            'async function adminServerState',
            'async function adminSetServerState',
            'requireAccountServiceEnabled(env)',
            'total_count: totalCount',
            'filtered_count: filteredCount',
            'url.pathname === "/v1/admin/server"',
        ),
    ),
    (
        "Main APK caches the user profile and performs temporary-ban expiry locally across app restarts",
        ".github/scripts/convert_account_gate_to_cloud.py",
        (
            "def apply_local_ban_cache",
            "ban_remaining_ms: i64",
            "ban_saved_at_ms: i64",
            "ban_clock_floor_ms: i64",
            "fn local_wall_clock_ms()",
            "fn current_ban_remaining_ms(&self)",
            "fn update_local_ban_timer(&mut self",
            "Instant::now()",
            "self.user = saved.user",
            "app.account.poll_events(config)",
            "临时封号已到期，本机已自动解封",
            "ban_clock_warning",
        ),
    ),
    (
        "Cloud ban responses and live events provide a server-calculated remaining duration",
        "cloudflare-worker/src/index.js",
        (
            "remaining_ms: remaining",
            "server_time_ms: Date.now()",
            "permanent: true",
        ),
    ),
    (
        "Reconnect event replay recalculates remaining ban duration instead of replaying a stale timer",
        "cloudflare-worker/src/account_session_hub.js",
        (
            "const remainingMs = event.status !==",
            "remaining_ms: remainingMs",
            "server_time_ms: Date.now()",
            "lastStatus.banned_until",
        ),
    ),
    (
        "Cloud account API supports permanent bans and complete online status notifications",
        "cloudflare-worker/src/index.js",
        (
            'String(row.banned_until).toLowerCase() === "permanent"',
            'bannedUntil = "permanent"',
            'until: bannedUntil',
            'reason: status === "banned" ? reason : ""',
        ),
    ),
    (
        "Account event hub replays ban status, expiry, and reason to reconnecting devices",
        "cloudflare-worker/src/account_session_hub.js",
        (
            'banned_until: lastStatus.banned_until || null',
            'until: lastStatus.banned_until || null',
            'reason: lastStatus.reason || ""',
            'changed_at: lastStatus.changed_at || null',
        ),
    ),
    (
        "Cloud D1 schema persists the account service switch without deleting account records",
        "cloudflare-worker/schema.sql",
        (
            'CREATE TABLE IF NOT EXISTS accounts',
            'CREATE TABLE IF NOT EXISTS account_service_state',
            'INSERT OR IGNORE INTO account_service_state',
        ),
    ),
    (
        "Main APK toolbar keeps all original controls reachable without duplicate overlapping Export buttons",
        ".github/scripts/make_header_scrollable.py",
        (
            'EFFECTCRAFT_ANDROID_RESPONSIVE_HEADER_SCROLL_V1',
            'ScrollArea::horizontal()',
            'exactly one Export button handler',
            'effectcraft-fixed-export-button',
            'All original buttons remain in their original order',
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
            "fn poll_events(&mut self)",
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
        "Android composition preview enlarges only the image while preserving every control position",
        ".github/scripts/set_android_default_workspace.py",
        (
            "EFFECTCRAFT_ANDROID_LARGER_COMPOSITION_NO_CONTROL_SHIFT_V1",
            "crates/ui-egui/src/panels/viewer.rs",
            "let fit_padding = 12.0;",
            "let fit_padding = 40.0;",
            "Dock geometry, panel boundaries, toolbars, buttons and their hit targets remain unchanged.",
            "all controls keep their original positions",
        ),
    ),
    (
        "Offline registration persists a local pending profile without storing the password and retries with backoff",
        ".github/scripts/add_offline_account_registration.py",
        (
            "PendingRegistration",
            "effectcraft-home-pending-registration.json",
            "self.local_only = true",
            "密码仅保留在当前运行内存",
            "std::time::Duration::from_secs(delay)",
            ".min(3600)",
            'response.status == 409',
            "maybe_retry_pending_registration",
            "立即同步本地账号",
            "no 10-second validation polling",
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
