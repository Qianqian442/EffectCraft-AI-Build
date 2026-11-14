#!/usr/bin/env python3
"""Convert the generated EffectCraft account gate to the shared HTTPS Cloudflare API."""
from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def clean_identical_duplicate_workspace_keys(source: str) -> tuple[str, bool]:
    """Remove only byte-for-byte equivalent repeated keys in the same TOML table."""
    lines = source.splitlines(keepends=True)
    output: list[str] = []
    seen: dict[tuple[str, int, str], tuple[int, str]] = {}
    table = ""
    array_table_index: dict[str, int] = {}
    changed = False

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped.startswith("[[") and stripped.endswith("]]"):
                table = stripped[2:-2].strip()
                array_table_index[table] = array_table_index.get(table, -1) + 1
            else:
                table = stripped[1:-1].strip()
            output.append(line)
            continue

        body = line.split("#", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9_-]+)\s*=\s*(.*?)\s*$", body)
        if not match:
            output.append(line)
            continue

        key, value = match.group(1), match.group(2)
        identity = (table, array_table_index.get(table, 0), key)
        previous = seen.get(identity)
        if previous is None:
            seen[identity] = (line_number, value)
            output.append(line)
            continue

        previous_line, previous_value = previous
        if value != previous_value:
            raise SystemExit(
                f"Workspace Cargo.toml has conflicting values for [{table}] {key}: "
                f"line {previous_line} has {previous_value!r}, line {line_number} has {value!r}; "
                "automatic merging was refused."
            )
        print(
            f"Removed identical duplicate workspace dependency [{table}] {key} "
            f"at line {line_number}; original is at line {previous_line}."
        )
        changed = True

    return "".join(output), changed


def validate_workspace_manifest(root: Path, source: str) -> str:
    try:
        tomllib.loads(source)
        return source
    except tomllib.TOMLDecodeError as original_error:
        cleaned, changed = clean_identical_duplicate_workspace_keys(source)
        if not changed:
            raise SystemExit(f"Invalid workspace Cargo.toml after account patch: {original_error}")
        try:
            tomllib.loads(cleaned)
        except tomllib.TOMLDecodeError as repaired_error:
            raise SystemExit(
                f"Workspace Cargo.toml is still invalid after removing identical duplicates: {repaired_error}"
            )
        (root / "Cargo.toml").write_text(cleaned, encoding="utf-8")
        print("Workspace Cargo.toml parsed successfully after safe duplicate cleanup.")
        return cleaned




def apply_local_ban_cache(source: str) -> str:
    """Persist ban decisions locally and expire temporary bans without startup polling."""
    # The offline-registration and avatar-picker patches both extend AccountState.
    # Remove the orphaned partial send-method prefix left at the join point before
    # the avatar picker methods; the complete send() definition follows those methods.
    source, orphan_count = re.subn(
        r"(?m)^    fn send\\(&mut self,\\s*(?=^    fn start_avatar_picker\\()",
        "",
        source,
        count=1,
    )
    if orphan_count != 1:
        raise SystemExit(
            f"account method join repair: expected one orphan send prefix, found {orphan_count}"
        )
    if source.count("    fn send(&mut self, action: Action") != 1:
        raise SystemExit("account method join repair: complete send method is missing or duplicated")
    saved_old = (
        "struct SavedAccount {\n"
        "    server_url: String,\n"
        "    token: String,\n"
        "}"
    )
    saved_new = (
        "struct SavedAccount {\n"
        "    server_url: String,\n"
        "    token: String,\n"
        "    #[serde(default)]\n"
        "    user: Option<User>,\n"
        "    #[serde(default)]\n"
        "    banned_until: Option<String>,\n"
        "    #[serde(default)]\n"
        "    ban_reason: String,\n"
        "    #[serde(default)]\n"
        "    ban_remaining_ms: i64,\n"
        "    #[serde(default)]\n"
        "    ban_saved_at_ms: i64,\n"
        "    #[serde(default)]\n"
        "    ban_clock_floor_ms: i64,\n"
        "}"
    )
    source = replace_once(source, saved_old, saved_new, "saved local ban state structure")

    source = replace_once(
        source,
        "    banned_until: String,\n    ban_reason: String,",
        "    banned_until: String,\n"
        "    ban_reason: String,\n"
        "    ban_remaining_ms: i64,\n"
        "    ban_saved_at_ms: i64,\n"
        "    ban_clock_floor_ms: i64,\n"
        "    ban_anchor: Option<Instant>,\n"
        "    ban_clock_warning: bool,",
        "local ban clock state fields",
    )
    source = replace_once(
        source,
        "            banned_until: String::new(),\n            ban_reason: String::new(),",
        "            banned_until: String::new(),\n"
        "            ban_reason: String::new(),\n"
        "            ban_remaining_ms: 0,\n"
        "            ban_saved_at_ms: 0,\n"
        "            ban_clock_floor_ms: 0,\n"
        "            ban_anchor: None,\n"
        "            ban_clock_warning: false,",
        "local ban clock state initialization",
    )

    source = replace_once(
        source,
        "impl AccountState {\n",
        "fn local_wall_clock_ms() -> i64 {\n"
        "    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default()\n"
        "        .as_millis().min(i64::MAX as u128) as i64\n"
        "}\n\n"
        "impl AccountState {\n"
        "    fn clear_local_ban(&mut self) {\n"
        "        self.banned_until.clear();\n"
        "        self.ban_reason.clear();\n"
        "        self.ban_remaining_ms = 0;\n"
        "        self.ban_saved_at_ms = local_wall_clock_ms();\n"
        "        self.ban_clock_floor_ms = self.ban_clock_floor_ms.max(self.ban_saved_at_ms);\n"
        "        self.ban_anchor = None;\n"
        "        self.ban_clock_warning = false;\n"
        "    }\n\n"
        "    fn current_ban_remaining_ms(&self) -> i64 {\n"
        "        if self.ban_remaining_ms < 0 { return -1; }\n"
        "        match self.ban_anchor {\n"
        "            Some(anchor) => self.ban_remaining_ms.saturating_sub(\n"
        "                anchor.elapsed().as_millis().min(i64::MAX as u128) as i64\n"
        "            ),\n"
        "            None => self.ban_remaining_ms,\n"
        "        }\n"
        "    }\n\n"
        "    fn update_local_ban_timer(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {\n"
        "        if self.mode != Mode::Banned || self.ban_remaining_ms < 0 || self.banned_until.eq_ignore_ascii_case(\"permanent\") || self.ban_clock_warning {\n"
        "            return;\n"
        "        }\n"
        "        if self.current_ban_remaining_ms() == 0 {\n"
        "            self.clear_local_ban();\n"
        "            self.mode = if self.user.is_some() { Mode::Editor } else { Mode::Auth };\n"
        "            self.status = \"临时封号已到期，本机已自动解封；联网后同步服务器\".to_string();\n"
        "            self.persist(config);\n"
        "        }\n"
        "    }\n",
        "local ban timer helpers",
    )

    startup_old = (
        "        if self.token.is_some() {\n"
        "            self.mode = Mode::Checking;\n"
        "            self.send(Action::Verify, \"GET\", \"/v1/me\", Value::Null, config);\n"
        "        } else if let Some(data) = config.and_then(|store| store.read(\"effectcraft-home-pending-registration.json\")) {\n"
        "            match serde_json::from_str::<PendingRegistration>(&data) {\n"
        "                Ok(pending) => {\n"
        "                    if !pending.server_url.is_empty() {\n"
        "                        self.server_url = pending.server_url.clone();\n"
        "                    }\n"
        "                    self.user = Some(pending.user.clone());\n"
        "                    self.pending_registration = Some(pending);\n"
        "                    self.local_only = true;\n"
        "                    self.mode = Mode::Editor;\n"
        "                    self.status = \"本地账号已保存，尚未同步到管理员账号节点。请打开“账号信息”输入密码完成同步。\".to_string();\n"
        "                }\n"
        "                Err(error) => {\n"
        "                    self.mode = Mode::Auth;\n"
        "                    self.status = format!(\"本地待同步账号资料无法读取：{error}\");\n"
        "                }\n"
        "            }\n"
        "        } else {\n"
        "            self.mode = Mode::Auth;\n"
        "        }"
    )
    startup_new = (
        "        if self.banned_until.eq_ignore_ascii_case(\"permanent\") || self.ban_remaining_ms < 0 {\n"
        "            self.ban_remaining_ms = -1;\n"
        "            self.mode = Mode::Banned;\n"
        "        } else if self.ban_remaining_ms > 0 {\n"
        "            let now = local_wall_clock_ms();\n"
        "            if now < self.ban_clock_floor_ms || now < self.ban_saved_at_ms {\n"
        "                self.ban_clock_warning = true;\n"
        "                self.mode = Mode::Banned;\n"
        "            } else {\n"
        "                let elapsed = now.saturating_sub(self.ban_saved_at_ms);\n"
        "                self.ban_remaining_ms = self.ban_remaining_ms.saturating_sub(elapsed);\n"
        "                self.ban_saved_at_ms = now;\n"
        "                self.ban_clock_floor_ms = self.ban_clock_floor_ms.max(now);\n"
        "                if self.ban_remaining_ms > 0 {\n"
        "                    self.ban_anchor = Some(Instant::now());\n"
        "                    self.mode = Mode::Banned;\n"
        "                } else {\n"
        "                    self.clear_local_ban();\n"
        "                    self.mode = if self.user.is_some() { Mode::Editor } else { Mode::Auth };\n"
        "                    self.status = \"临时封号已到期，本机已自动解封；联网后同步服务器\".to_string();\n"
        "                }\n"
        "            }\n"
        "        } else if self.user.is_some() {\n"
        "            self.mode = Mode::Editor;\n"
        "        } else if self.token.is_some() {\n"
        "            // One-time compatibility verification for older token-only saved profiles.\n"
        "            self.mode = Mode::Checking;\n"
        "            self.send(Action::Verify, \"GET\", \"/v1/me\", Value::Null, config);\n"
        "        } else if let Some(data) = config.and_then(|store| store.read(\"effectcraft-home-pending-registration.json\")) {\n"
        "            match serde_json::from_str::<PendingRegistration>(&data) {\n"
        "                Ok(pending) => {\n"
        "                    if !pending.server_url.is_empty() { self.server_url = pending.server_url.clone(); }\n"
        "                    self.user = Some(pending.user.clone());\n"
        "                    self.pending_registration = Some(pending);\n"
        "                    self.local_only = true;\n"
        "                    self.mode = Mode::Editor;\n"
        "                    self.status = \"本地账号已保存，尚未同步到云端账号库。请打开“账号信息”输入密码完成同步。\".to_string();\n"
        "                }\n"
        "                Err(error) => {\n"
        "                    self.mode = Mode::Auth;\n"
        "                    self.status = format!(\"本地待同步账号资料无法读取：{error}\");\n"
        "                }\n"
        "            }\n"
        "        } else {\n"
        "            self.mode = Mode::Auth;\n"
        "        }"
    )
    source = replace_once(source, startup_old, startup_new, "offline-first account startup")

    persist_old = (
        "    fn persist(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {\n"
        "        let (Some(store), Some(token)) = (config, self.token.as_ref()) else {\n"
        "            return;\n"
        "        };\n"
        "        let saved = SavedAccount { server_url: self.server_url.clone(), token: token.clone() };\n"
        "        if let Ok(data) = serde_json::to_string(&saved) {\n"
        "            let _ = store.write(\"effectcraft-home-account.json\", &data);\n"
        "        }\n"
        "    }"
    )
    persist_new = (
        "    fn persist(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {\n"
        "        let (Some(store), Some(token)) = (config, self.token.as_ref()) else { return; };\n"
        "        let now = local_wall_clock_ms();\n"
        "        let remaining = self.current_ban_remaining_ms();\n"
        "        let saved = SavedAccount {\n"
        "            server_url: self.server_url.clone(),\n"
        "            token: token.clone(),\n"
        "            user: self.user.clone(),\n"
        "            banned_until: if remaining == 0 { None } else { Some(self.banned_until.clone()) },\n"
        "            ban_reason: if remaining == 0 { String::new() } else { self.ban_reason.clone() },\n"
        "            ban_remaining_ms: remaining,\n"
        "            ban_saved_at_ms: now,\n"
        "            ban_clock_floor_ms: self.ban_clock_floor_ms.max(now),\n"
        "        };\n"
        "        if let Ok(data) = serde_json::to_string(&saved) {\n"
        "            let _ = store.write(\"effectcraft-home-account.json\", &data);\n"
        "        }\n"
        "    }"
    )
    source = replace_once(source, persist_old, persist_new, "persist cached account and ban expiry")

    banned_old = (
        "                self.banned_until = detail.get(\"until\").and_then(Value::as_str).unwrap_or(\"时间未知\").to_string();\n"
        "                self.ban_reason = detail.get(\"reason\").and_then(Value::as_str).unwrap_or(\"未填写原因\").to_string();\n"
        "                self.mode = Mode::Banned;\n"
        "                self.status.clear();"
    )
    banned_new = (
        "                self.banned_until = detail.get(\"until\").and_then(Value::as_str).unwrap_or(\"时间未知\").to_string();\n"
        "                self.ban_reason = detail.get(\"reason\").and_then(Value::as_str).unwrap_or(\"未填写原因\").to_string();\n"
        "                self.ban_remaining_ms = if self.banned_until.eq_ignore_ascii_case(\"permanent\") { -1 } else { detail.get(\"remaining_ms\").and_then(Value::as_i64).map(|value| value.max(0)).unwrap_or(-1) };\n"
        "                self.ban_saved_at_ms = local_wall_clock_ms();\n"
        "                self.ban_clock_floor_ms = self.ban_saved_at_ms;\n"
        "                self.ban_anchor = if self.ban_remaining_ms > 0 { Some(Instant::now()) } else { None };\n"
        "                self.ban_clock_warning = false;\n"
        "                self.mode = Mode::Banned;\n"
        "                self.status.clear();\n"
        "                self.persist(config);"
    )
    source = replace_once(source, banned_old, banned_new, "local cache for authenticated ban response")

    # Extend the generated WebSocket handler with a local monotonic countdown.
    poll_events_pattern = re.compile(
        r"    fn poll_events\(&mut self\) \{.*?\n    \}\n",
        re.S,
    )
    local_events = r'''    fn poll_events(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if self.token.is_some() && !self.event_started {
            self.start_events();
        }
        let received = match self.events.as_ref().map(|rx| rx.try_recv()) {
            Some(Ok(result)) => Some(result),
            Some(Err(TryRecvError::Disconnected)) => Some(Err("实时封禁通知通道已结束".to_string())),
            Some(Err(TryRecvError::Empty)) | None => None,
        };
        match received {
            Some(Ok(event)) if event.get("type").and_then(Value::as_str) == Some("account_status_changed") => {
                match event.get("status").and_then(Value::as_str).unwrap_or("") {
                    "banned" => {
                        self.banned_until = event.get("banned_until").or_else(|| event.get("until")).and_then(Value::as_str).unwrap_or("时间未知").to_string();
                        self.ban_reason = event.get("reason").and_then(Value::as_str).unwrap_or("未填写原因").to_string();
                        self.ban_remaining_ms = if self.banned_until.eq_ignore_ascii_case("permanent") {
                            -1
                        } else {
                            event.get("remaining_ms").and_then(Value::as_i64).map(|value| value.max(0)).unwrap_or(-1)
                        };
                        self.ban_saved_at_ms = local_wall_clock_ms();
                        self.ban_clock_floor_ms = self.ban_saved_at_ms;
                        self.ban_anchor = if self.ban_remaining_ms > 0 { Some(Instant::now()) } else { None };
                        self.ban_clock_warning = false;
                        if self.ban_remaining_ms == 0 {
                            self.clear_local_ban();
                            self.mode = if self.user.is_some() { Mode::Editor } else { Mode::Auth };
                            self.status = "临时封号已到期，本机已自动解封".to_string();
                        } else {
                            self.mode = Mode::Banned;
                            self.status = "管理员已封禁此账号".to_string();
                        }
                        self.persist(config);
                    }
                    "unbanned" => {
                        self.clear_local_ban();
                        if self.user.is_some() {
                            self.mode = Mode::Editor;
                            self.status = "管理员已解除封禁".to_string();
                        }
                        self.persist(config);
                    }
                    _ => {}
                }
            }
            Some(Err(error)) => self.status = error,
            None => {}
        }
    }'''
    source, count = poll_events_pattern.subn(lambda _m: local_events + "\n", source, count=1)
    if count != 1:
        raise SystemExit(f"local ban event handler: expected one poll_events method, found {count}")

    source = replace_once(
        source,
        "    app.account.poll_events();",
        "    app.account.poll_events(config);\n    app.account.update_local_ban_timer(config);",
        "local ban expiry frame update",
    )
    ban_ui_old = (
        "                ui.label(format!(\"封禁截止时间：{}\", app.account.banned_until));\n"
        "                ui.add_space(8.0);\n"
        "                ui.label(\"封禁原因：\");"
    )
    ban_ui_new = (
        "                if app.account.banned_until.eq_ignore_ascii_case(\"permanent\") {\n"
        "                    ui.label(\"封禁期限：永久封号\");\n"
        "                } else if app.account.ban_remaining_ms < 0 {\n"
        "                    ui.label(\"封禁剩余时间暂不可确认，继续保持封禁；联网同步后再判断。\");\n"
        "                } else if app.account.ban_clock_warning {\n"
        "                    ui.label(\"设备时间发生回拨，继续保持封禁；恢复自动设置时间或联网校准后再判断到期。\");\n"
        "                } else {\n"
        "                    let seconds = (app.account.current_ban_remaining_ms().max(0) + 999) / 1000;\n"
        "                    ui.label(format!(\"本机剩余封禁时间：{}天 {:02}:{:02}:{:02}\", seconds / 86400, (seconds % 86400) / 3600, (seconds % 3600) / 60, seconds % 60));\n"
        "                    ui.label(format!(\"封禁截止时间：{}\", app.account.banned_until));\n"
        "                }\n"
        "                ui.add_space(8.0);\n"
        "                ui.label(\"封禁原因：\");"
    )
    source = replace_once(source, ban_ui_old, ban_ui_new, "show local ban countdown")
    return source

def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"])
    account_path = root / "crates/ui-egui/src/account.rs"
    if not account_path.is_file():
        raise SystemExit("Run add_home_lan_account_gate.py before the cloud account patch.")

    api_url = os.environ.get("AE_ACCOUNT_API_URL", "").strip().rstrip("/")
    if not api_url.startswith("https://"):
        raise SystemExit(
            "AE_ACCOUNT_API_URL must be the deployed primary HTTPS account API URL. "
            "Deploy cloudflare-worker first; do not publish a LAN/P2P-only APK."
        )
    api_urls = []
    for candidate in [api_url, *os.environ.get("AE_ACCOUNT_API_URLS", "").split(";")]:
        candidate = candidate.strip().rstrip("/")
        if candidate and candidate not in api_urls:
            if not candidate.startswith("https://") or "@" in candidate:
                raise SystemExit(f"Invalid backup account API URL: {candidate!r}; HTTPS is required.")
            api_urls.append(candidate)
    pool_source = "const API_SERVER_POOL: &[&str] = &[\n" + "".join(
        f"    {json.dumps(candidate)},\n" for candidate in api_urls
    ) + "];\n"
    server_switch_helper = """
fn next_api_server(current: &str) -> Option<&'static str> {
    if API_SERVER_POOL.len() < 2 {
        return None;
    }
    let index = API_SERVER_POOL.iter().position(|candidate| *candidate == current).unwrap_or(0);
    Some(API_SERVER_POOL[(index + 1) % API_SERVER_POOL.len()])
}

"""

    source = account_path.read_text(encoding="utf-8")
    if "EFFECTCRAFT_HOME_LAN_ACCOUNT_GATE_V1" not in source:
        raise SystemExit("Unexpected account.rs source; the home account gate marker is missing.")

    source = replace_once(
        source,
        "//! Home-Wi-Fi-only account gate. The account API is intentionally fail-closed:\n"
        "//! when a saved account cannot be checked against the home server, the editor stays locked.",
        "//! Cloud HTTPS account gate. The account API is intentionally fail-closed:\n"
        "//! when a saved account cannot be checked against Cloudflare, the editor stays locked.",
        "account module documentation",
    )

    # Replace the legacy local transport imports/constants while preserving the
    # optional image-picker base64 trait import inserted by add_account_avatar_picker.py.
    imports_pattern = re.compile(
        r"use std::io::\{BufRead, BufReader, Read, Write\};\r?\n"
        r"use std::net::\{TcpListener, TcpStream, ToSocketAddrs\};\r?\n"
        r"use std::sync::atomic::\{AtomicBool, Ordering\};\r?\n"
        r"use std::sync::mpsc::\{self, Receiver, TryRecvError\};\r?\n"
        r"use std::time::Duration;\r?\n"
        r"(use base64::Engine as _;\r?\n)?"
        r"\r?\n"
        r'const DEFAULT_SERVER: &str = "p2p://auto";\r?\n'
        r"const ACCOUNT_EVENT_PROXY: std::net::SocketAddr = std::net::SocketAddr::new\(\r?\n"
        r"\s*std::net::IpAddr::V4\(std::net::Ipv4Addr::LOCALHOST\), 8790,\r?\n"
        r"\);\r?\n"
        r"static ACCOUNT_EVENT_LISTENER_STARTED: AtomicBool = AtomicBool::new\(false\);\r?\n",
        re.M,
    )
    import_match = imports_pattern.search(source)
    if not import_match:
        raise SystemExit("Could not locate the legacy account transport imports/constants (including optional avatar picker import).")
    base64_import = import_match.group(1) or ""
    new_imports = (
        "use std::io::Read;\n"
        "use std::sync::mpsc::{self, Receiver, TryRecvError};\n"
        "use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};\n"
        + base64_import
        + "use tungstenite::client::IntoClientRequest;\n"
        + "use tungstenite::http::HeaderValue;\n"
        + "use tungstenite::Message;\n\n"
        + f'const DEFAULT_SERVER: &str = "{api_url}";\n'
        + pool_source
        + server_switch_helper
    )
    source, import_count = imports_pattern.subn(lambda _match: new_imports, source, count=1)
    if import_count != 1:
        raise SystemExit(f"imports and cloud API URL: expected one match, found {import_count}")

    # Remove the old local TCP event listener. Cloud ban/unban state comes from
    # the authenticated Cloudflare Durable Object WebSocket, not the admin phone.
    listener_pattern = re.compile(
        r"fn start_account_event_listener\(\) -> Option<Receiver<Value>> \{.*?\n\}\n\n(?=#\[derive\(Clone, Copy, Debug, Default)",
        re.S,
    )
    source, n = listener_pattern.subn("", source, count=1)
    if n != 1:
        raise SystemExit(f"local TCP event listener removal expected once, found {n}")

    source = replace_once(
        source,
        "    events: Option<Receiver<Value>>,",
        "    events: Option<Receiver<Result<Value, String>>>,\n    event_started: bool,",
        "cloud event receiver field",
    )
    source = replace_once(
        source,
        "            events: None,",
        "            events: None,\n            event_started: false,",
        "cloud event receiver initialization",
    )
    source = replace_once(
        source,
        "        if self.events.is_none() {\n"
        "            self.events = start_account_event_listener();\n"
        "        }\n",
        "",
        "remove local event-listener startup",
    )

    old_saved = (
        "                    // Preserve an explicitly pinned administrator identity. Upgrade\n"
        "                    // legacy LAN profiles to auto-discovery without discarding tokens.\n"
        "                    self.server_url = if saved.server_url.starts_with(\"p2p://\") {\n"
        "                        saved.server_url\n"
        "                    } else {\n"
        "                        DEFAULT_SERVER.to_string()\n"
        "                    };\n"
        "                    if !saved.token.is_empty() {\n"
        "                        self.token = Some(saved.token);\n"
        "                    }"
    )
    new_saved = (
        "                    // Restore cached account and ban state only for this configured HTTPS authority.\n"
        "                    if saved.server_url == self.server_url {\n"
        "                        if !saved.token.is_empty() { self.token = Some(saved.token); }\n"
        "                        self.user = saved.user;\n"
        "                        self.banned_until = saved.banned_until.unwrap_or_default();\n"
        "                        self.ban_reason = saved.ban_reason;\n"
        "                        self.ban_remaining_ms = saved.ban_remaining_ms;\n"
        "                        self.ban_saved_at_ms = saved.ban_saved_at_ms;\n"
        "                        self.ban_clock_floor_ms = saved.ban_clock_floor_ms;\n"
        "                    }"
    )
    source = replace_once(source, old_saved, new_saved, "saved account server migration")
    source = source.replace(
        'self.status = "正在连接管理员账号节点…".to_string();',
        'self.status = "正在连接云端 HTTPS 账号服务…".to_string();',
    )
    source = source.replace(
        'self.status = format!("无法连接家中的账号服务器：{error}");',
        'self.status = format!("无法连接云端 HTTPS 账号服务器：{error}");',
    )

    source = source.replace(
        'self.status = format!("无法连接管理员账号节点：{error}");',
        'self.status = format!("无法连接云端 HTTPS 账号服务器：{error}");',
    )
    source = source.replace(
        '"本地注册完成 · 待同步到管理员账号节点"',
        '"本地注册完成 · 待同步到云端账号库"',
    )
    source = source.replace(
        '"管理员节点 ID（p2p://…）"',
        '"云端 HTTPS 服务器地址"',
    )
    source = source.replace(
        'ui.text_edit_singleline(&mut app.account.server_url);',
        'ui.label(&app.account.server_url);',
    )
    source = source.replace(
        '"本地账号资料已更新，仍待管理员节点同步。"',
        '"本地账号资料已更新，仍待同步到云端账号库。"',
    )

    live_events = r'''
    fn start_events(&mut self) {
        if self.event_started {
            return;
        }
        let Some(token) = self.token.clone() else { return; };
        let mut ws_urls = Vec::<String>::new();
        for endpoint in std::iter::once(self.server_url.as_str()).chain(API_SERVER_POOL.iter().copied()) {
            if !endpoint.starts_with("https://") { continue; }
            let base = endpoint.trim_end_matches('/').replacen("https://", "wss://", 1);
            let candidate = format!("{base}/v1/events");
            if !ws_urls.contains(&candidate) {
                ws_urls.push(candidate);
            }
        }
        let (tx, rx) = mpsc::channel();
        self.events = Some(rx);
        self.event_started = true;
        std::thread::spawn(move || {
            let mut reconnect_delay = 3u64;
            loop {
                let mut connected = false;
                let mut last_error = String::new();
                for ws_url in &ws_urls {
                    let mut request = match ws_url.clone().into_client_request() {
                        Ok(request) => request,
                        Err(error) => {
                            last_error = format!("实时封禁通知地址无效：{error}");
                            continue;
                        }
                    };
                    let authorization = match HeaderValue::from_str(&format!("Bearer {token}")) {
                        Ok(value) => value,
                        Err(_) => {
                            let _ = tx.send(Err("账号登录凭据格式不正确".to_string()));
                            return;
                        }
                    };
                    request.headers_mut().insert("Authorization", authorization);
                    match tungstenite::connect(request) {
                        Ok((mut socket, _)) => {
                            connected = true;
                            reconnect_delay = 3;
                            loop {
                                match socket.read() {
                                    Ok(Message::Text(message)) => {
                                        if let Ok(value) = serde_json::from_str::<Value>(message.as_str()) {
                                            if tx.send(Ok(value)).is_err() { return; }
                                        }
                                    }
                                    Ok(Message::Close(_)) => break,
                                    Ok(_) => {}
                                    Err(_) => break,
                                }
                            }
                            break;
                        }
                        Err(error) => {
                            last_error = format!("{ws_url}：{error}");
                        }
                    }
                }
                if !connected {
                    let _ = tx.send(Err(format!("所有实时通知入口均无法连接：{last_error}")));
                }
                std::thread::sleep(Duration::from_secs(reconnect_delay));
                reconnect_delay = (reconnect_delay * 2).min(600);
            }
        });
    }

    fn poll_events(&mut self) {
        if self.token.is_some() && !self.event_started {
            self.start_events();
        }
        let received = match self.events.as_ref().map(|rx| rx.try_recv()) {
            Some(Ok(result)) => Some(result),
            Some(Err(TryRecvError::Disconnected)) => Some(Err("实时封禁通知通道已结束".to_string())),
            Some(Err(TryRecvError::Empty)) | None => None,
        };
        match received {
            Some(Ok(event)) if event.get("type").and_then(Value::as_str) == Some("account_status_changed") => {
                match event.get("status").and_then(Value::as_str).unwrap_or("") {
                    "banned" => {
                        self.banned_until = event.get("until").and_then(Value::as_str).unwrap_or("时间未知").to_string();
                        self.ban_reason = event.get("reason").and_then(Value::as_str).unwrap_or("未填写原因").to_string();
                        self.mode = Mode::Banned;
                        self.status = "管理员已封禁此账号".to_string();
                    }
                    "unbanned" => {
                        self.banned_until.clear();
                        self.ban_reason.clear();
                        if self.user.is_some() {
                            self.mode = Mode::Editor;
                            self.status = "管理员已解除封禁".to_string();
                        }
                    }
                    _ => {}
                }
            }
            Some(Err(error)) => {
                self.status = error;
            }
            None => {}
        }
    }
'''
    event_pattern = re.compile(
        r"    fn poll_events\(&mut self\) \{.*?\n    \}\n\n    fn retry\(",
        re.S,
    )
    source, n = event_pattern.subn(live_events + "\n    fn retry(", source, count=1)
    if n != 1:
        raise SystemExit(f"cloud WebSocket event implementation expected one replacement, found {n}")

    source = apply_local_ban_cache(source)

    http_replacement = r'''fn http_request(url: &str, method: &str, path: &str, body: Value, token: Option<&str>) -> Result<HttpResult, String> {
    let mut candidates = Vec::<&str>::new();
    if url.starts_with("https://") {
        candidates.push(url.trim_end_matches('/'));
    }
    for candidate in API_SERVER_POOL {
        if !candidates.contains(candidate) {
            candidates.push(candidate);
        }
    }
    let mut last_error = String::new();
    let mut last_server_error = None;
    for candidate in candidates {
        match http_request_single(candidate, method, path, body.clone(), token) {
            Ok(response) if response.status >= 500 => {
                last_error = format!("{candidate} 返回 HTTP {}", response.status);
                last_server_error = Some(response);
            }
            Ok(response) => return Ok(response),
            Err(error) => last_error = format!("{candidate}：{error}"),
        }
    }
    if let Some(response) = last_server_error {
        return Ok(response);
    }
    Err(format!("所有已配置的云端 HTTPS 入口均不可用：{last_error}"))
}

fn http_request_single(url: &str, method: &str, path: &str, body: Value, token: Option<&str>) -> Result<HttpResult, String> {
    if !url.starts_with("https://") {
        return Err("账号服务必须使用 HTTPS 云端地址".to_string());
    }
    let endpoint = format!("{}{}", url.trim_end_matches('/'), path);
    let agent: ureq::Agent = ureq::Agent::config_builder()
        .http_status_as_error(false)
        .timeout_global(Some(Duration::from_secs(10)))
        .build()
        .into();
    let mut request = if method == "GET" { agent.get(&endpoint) } else { agent.post(&endpoint) };
    request = request.header("Accept", "application/json");
    if let Some(token) = token {
        request = request.header("Authorization", &format!("Bearer {token}"));
    }
    let mut response = if body.is_null() {
        request.call()
    } else {
        let bytes = serde_json::to_vec(&body).map_err(|error| error.to_string())?;
        request.header("Content-Type", "application/json").send(bytes.as_slice())
    }.map_err(|error| format!("云端 HTTPS 请求失败：{error}"))?;
    let status = response.status().as_u16();
    let mut body_text = String::new();
    response.body_mut().read_to_string(&mut body_text).map_err(|error| error.to_string())?;
    let value = serde_json::from_str::<Value>(&body_text)
        .unwrap_or_else(|_| json!({"detail": "服务器返回了无法识别的数据"}));
    Ok(HttpResult { status, body: value })
}

'''
    http_pattern = re.compile(
        r"fn http_request\(url: &str, method: &str, path: &str, body: Value, token: Option<&str>\) -> Result<HttpResult, String> \{.*?\n\}\n\n(?=fn blocking_overlay)",
        re.S,
    )
    source, n = http_pattern.subn(http_replacement, source, count=1)
    if n != 1:
        raise SystemExit(f"HTTP/P2P transport replacement expected one match, found {n}")

    source = source.replace(
        'ui.label("通过 P2P 自动连接管理员手机账号节点");',
        'ui.label("通过 HTTPS 连接云端账号服务，可跨城市和不同网络使用");',
    )
    source = source.replace(
        '            ui.label(&app.account.server_url);\n',
        '            ui.label(&app.account.server_url);\n'
        '            if ui.button("切换服务器").clicked() {\n'
        '                if let Some(next) = next_api_server(&app.account.server_url) {\n'
        '                    app.account.server_url = next.to_string();\n'
        '                    app.account.retry(config);\n'
        '                } else {\n'
        '                    app.account.status = "目前只配置了一个云端入口；备用入口需部署并指向同一账号数据库".to_string();\n'
        '                }\n'
        '            }\n',
    )
    source = source.replace(
        '                    if ui.button("账号信息").clicked() {',
        '                    if ui.button("切换服务器").clicked() {\n'
        '                        if let Some(next) = next_api_server(&app.account.server_url) {\n'
        '                            app.account.server_url = next.to_string();\n'
        '                            app.account.retry(config);\n'
        '                        } else {\n'
        '                            app.account.status = "目前只配置了一个云端入口；备用入口需部署并指向同一账号数据库".to_string();\n'
        '                        }\n'
        '                    }\n'
        '                    if ui.button("账号信息").clicked() {',
    )

    source = source.replace(
        'ui.label("账号节点连接方式");\n            ui.text_edit_singleline(&mut app.account.server_url);\n'
        '            ui.small("请首次填写管理版复制的完整 p2p://管理员节点ID。为防止假节点窃取密码，未固定管理员身份前不会发送账号密码；保存后以后自动连接，无需逐次审批。");',
        'ui.label("云端账号服务器（HTTPS）");\n'
        '            ui.label(&app.account.server_url);\n'
        '            ui.small("主 APK 与管理版共用同一个云端账号数据库；管理员封禁/解禁会实时通知在线设备。");',
    )
    source = source.replace(
        'ui.heading("正在连接家庭账号服务器");',
        'ui.heading("正在连接云端 HTTPS 账号服务器");',
    )
    source = source.replace(
        'ui.label("管理员手机账号节点当前无法连接。为防止离线绕过封禁，软件暂时保持锁定。");\n'
        '            ui.label("请粘贴管理版“复制管理员节点 ID”得到的完整 p2p://地址；同 Wi-Fi 优先直连，跨网络自动尝试打洞和公共中继。");\n'
        '            ui.label("管理员节点地址");\n'
        '            ui.text_edit_singleline(&mut app.account.server_url);\n'
        '            if ui.add_enabled(app.account.pending.is_none(), egui::Button::new("保存节点地址并重新连接")).clicked() {\n'
        '                app.account.retry(config);\n'
        '            }',
        'ui.label("云端 HTTPS 账号服务器当前无法连接。为防止离线绕过封禁，软件暂时保持锁定。");\n'
        '            ui.label("请检查手机网络或云端服务状态，然后重新验证账号。");\n'
        '            ui.label("云端地址");\n'
        '            ui.label(&app.account.server_url);\n'
        '            if ui.add_enabled(app.account.pending.is_none(), egui::Button::new("重新连接云端")).clicked() {\n'
        '                app.account.retry(config);\n'
        '            }',
    )

    if "p2p_account_request" in source or "TcpListener" in source or "p2p://auto" in source:
        raise SystemExit("P2P/LAN account transport remains after HTTPS conversion.")
    if "last_verified" in source:
        raise SystemExit("Unexpected periodic account polling code remains.")
    account_path.write_text(source, encoding="utf-8")

    workspace_manifest = root / "Cargo.toml"
    workspace = workspace_manifest.read_text(encoding="utf-8")
    workspace_additions: list[str] = []
    # Upstream workspaces may already define ureq with a compatible version or
    # feature set. Reuse that declaration instead of adding a conflicting second key.
    if not re.search(r"(?m)^ureq\s*=", workspace):
        workspace_additions.append('ureq = "3.5"\n')
    if not re.search(r"(?m)^tungstenite\s*=", workspace):
        workspace_additions.append(
            'tungstenite = { version = "0.30", default-features = false, features = ["handshake", "rustls-tls-webpki-roots"] }\n'
        )
    if workspace_additions:
        anchor = 'serde_json = { version = "1", features = ["float_roundtrip"] }\n'
        if anchor not in workspace:
            raise SystemExit("Could not add HTTPS dependencies: workspace serde_json anchor is missing.")
        workspace = workspace.replace(anchor, anchor + "".join(workspace_additions), 1)
        workspace_manifest.write_text(workspace, encoding="utf-8")

    # The Android launcher generator parses the entire workspace manifest. Validate
    # after all earlier root-manifest patches (AM/NV, ZIP plug-ins, and HTTPS) have run.
    workspace = validate_workspace_manifest(root, workspace)

    ui_manifest = root / "crates/ui-egui/Cargo.toml"
    ui = ui_manifest.read_text(encoding="utf-8")
    ui_additions: list[str] = []
    if not re.search(r"(?m)^ureq\s*=", ui):
        ui_additions.append('ureq = { workspace = true }\n')
    if not re.search(r"(?m)^tungstenite\s*=", ui):
        ui_additions.append('tungstenite = { workspace = true }\n')
    if ui_additions:
        anchor = 'image = { workspace = true }\n'
        if anchor not in ui:
            raise SystemExit("Could not add HTTPS dependencies: UI image dependency anchor is missing.")
        ui = ui.replace(anchor, anchor + "".join(ui_additions), 1)
        ui_manifest.write_text(ui, encoding="utf-8")

    if "fn http_request_single" not in source or "API_SERVER_POOL" not in source or "切换服务器" not in source:
        raise SystemExit("Cloud endpoint failover or server-switch controls were not installed.")
    print(f"Cloud HTTPS account gate installed with {len(api_urls)} configured endpoint(s), automatic failover, and live ban/unban notifications; no periodic polling.")


if __name__ == "__main__":
    main()
