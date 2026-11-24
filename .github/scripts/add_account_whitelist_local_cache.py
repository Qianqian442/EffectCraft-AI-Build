#!/usr/bin/env python3
"""Install local whitelist prechecks and offline-persisted ban state into the Cloudflare account client."""
from __future__ import annotations

import os
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    account_path = root / "crates/ui-egui/src/account.rs"
    source = account_path.read_text(encoding="utf-8")
    marker = "EFFECTCRAFT_LOCAL_WHITELIST_AND_OFFLINE_BAN_V1"
    if marker in source:
        print("Local whitelist cache and offline ban state are already installed.")
        return

    source = replace_once(
        source,
        "use serde_json::{Value, json};",
        "use serde_json::{Value, json};\nuse sha2::{Digest, Sha256};\nuse chrono::DateTime;",
        "whitelist hashing and ban countdown imports",
    )
    source = replace_once(source, "    Profile,\n}", "    Profile,\n    Whitelist,\n}", "add whitelist fetch action")

    saved_types = r"""
// EFFECTCRAFT_LOCAL_WHITELIST_AND_OFFLINE_BAN_V1
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct SavedWhitelist {
    #[serde(default)]
    revision: String,
    #[serde(default)]
    qq_hashes: Vec<String>,
    #[serde(default)]
    wechat_hashes: Vec<String>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct SavedBan {
    #[serde(default)]
    until: String,
    #[serde(default)]
    reason: String,
}
fn identifier_digest(kind: &str, value: &str) -> String {
    let normalized = if kind == "wechat" {
        value.trim().to_ascii_lowercase()
    } else {
        value.trim().to_string()
    };
    let mut digest = Sha256::new();
    digest.update(kind.as_bytes());
    digest.update(b":");
    digest.update(normalized.as_bytes());
    digest.finalize().iter().map(|byte| format!("{byte:02x}")).collect()
}
"""
    source = replace_once(
        source,
        "struct HttpResult {\n    status: u16,\n    body: Value,\n}\n",
        saved_types + "\nstruct HttpResult {\n    status: u16,\n    body: Value,\n}\n",
        "add local whitelist and ban cache models",
    )
    source = replace_once(
        source,
        "    ban_reason: String,\n    verified_at: u64,\n    status: String,",
        "    ban_reason: String,\n    verified_at: u64,\n    whitelist: SavedWhitelist,\n    whitelist_ready: bool,\n    status: String,",
        "add local whitelist state",
    )
    source = replace_once(
        source,
        "            ban_reason: String::new(),\n            verified_at: 0,\n            status: String::new(),",
        "            ban_reason: String::new(),\n            verified_at: 0,\n            whitelist: SavedWhitelist::default(),\n            whitelist_ready: false,\n            status: String::new(),",
        "initialize local whitelist state",
    )

    old_startup = '''        if self.token.is_some() {
            self.mode = Mode::Checking;
            self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
        } else {
            self.mode = Mode::Auth;
        }'''
    new_startup = r'''        // A previously received ban is stored in app-private config. Display it
        // immediately when reopening, without contacting Cloudflare.
        if let Some(raw) = config.and_then(|store| store.read("effectcraft-account-ban.json")) {
            if let Ok(saved_ban) = serde_json::from_str::<SavedBan>(&raw) {
                self.banned_until = saved_ban.until;
                self.ban_reason = saved_ban.reason;
                self.mode = Mode::Banned;
                self.status.clear();
                return;
            }
        }
        if let Some(raw) = config.and_then(|store| store.read("effectcraft-account-whitelist.json")) {
            if let Ok(saved) = serde_json::from_str::<SavedWhitelist>(&raw) {
                self.whitelist_ready = !saved.revision.is_empty();
                self.whitelist = saved;
            }
        }
        self.mode = if self.token.is_some() { Mode::Checking } else { Mode::Auth };
        // Refresh the local whitelist once on startup. If this request fails, the
        // previously downloaded app-private hash snapshot remains available.
        self.send(Action::Whitelist, "GET", "/v1/whitelist", Value::Null, config);'''
    source = replace_once(source, old_startup, new_startup, "load local ban and refresh whitelist on startup")

    methods = r'''
    fn whitelist_has(&self, kind: &str, value: &str) -> bool {
        if !self.whitelist_ready || value.trim().is_empty() { return false; }
        let digest = identifier_digest(kind, value);
        if kind == "qq" {
            self.whitelist.qq_hashes.iter().any(|entry| entry == &digest)
        } else {
            self.whitelist.wechat_hashes.iter().any(|entry| entry == &digest)
        }
    }

    fn persist_ban(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if let Some(store) = config {
            let saved = SavedBan { until: self.banned_until.clone(), reason: self.ban_reason.clone() };
            if let Ok(data) = serde_json::to_string(&saved) {
                let _ = store.write("effectcraft-account-ban.json", &data);
            }
        }
    }

    fn clear_cached_ban(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if let Some(store) = config {
            let _ = store.remove("effectcraft-account-ban.json");
        }
    }

    fn ban_countdown_label(&self) -> String {
        if self.banned_until.eq_ignore_ascii_case("PERMANENT") {
            return "永久封号；只有管理员手动解封后才能恢复。".to_string();
        }
        match DateTime::parse_from_rfc3339(&self.banned_until) {
            Ok(until) => {
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs()
                    .min(i64::MAX as u64) as i64;
                let seconds = (until.timestamp() - now).max(0);
                if seconds == 0 {
                    "封禁截止时间已到；需要联网核验管理员是否已解封。".to_string()
                } else {
                    let days = seconds / 86400;
                    let hours = (seconds % 86400) / 3600;
                    let minutes = (seconds % 3600) / 60;
                    let secs = seconds % 60;
                    format!("本地封禁剩余：{}天 {}小时 {}分 {}秒", days, hours, minutes, secs)
                }
            }
            Err(_) => "封禁时间暂不可识别。".to_string(),
        }
    }

'''
    source = replace_once(
        source,
        "    fn submit_login(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {",
        methods + "    fn submit_login(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {",
        "add whitelist and local ban helpers",
    )
    source = replace_once(
        source,
        '''    fn submit_login(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        self.send(''',
        '''    fn submit_login(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if !self.whitelist_ready {
            self.status = "本机白名单尚未下载，请连接网络后重试。".to_string();
            return;
        }
        let identifier = self.login_identifier.trim();
        let kind = if identifier.bytes().all(|byte| byte.is_ascii_digit()) { "qq" } else { "wechat" };
        if !self.whitelist_has(kind, identifier) {
            self.status = if kind == "qq" {
                "该 QQ号不在本机白名单中，不能登录。".to_string()
            } else {
                "该微信号不在本机白名单中，不能登录。".to_string()
            };
            return;
        }
        self.send(''',
        "local whitelist check before login",
    )
    source = replace_once(
        source,
        '''    fn submit_register(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        self.send(''',
        '''    fn submit_register(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if !self.whitelist_ready {
            self.status = "本机白名单尚未下载，请连接网络后重试。".to_string();
            return;
        }
        let qq = self.qq.trim();
        let wechat = self.wechat.trim();
        if qq.is_empty() && wechat.is_empty() {
            self.status = "QQ号和微信号至少填写一项。".to_string();
            return;
        }
        if (!qq.is_empty() && !self.whitelist_has("qq", qq))
            || (!wechat.is_empty() && !self.whitelist_has("wechat", wechat)) {
            self.status = "填写的 QQ号或微信号不在本机白名单中，不能注册。".to_string();
            return;
        }
        self.send(''',
        "local whitelist check before registration",
    )

    source = replace_once(
        source,
        '''            Ok(response) if response.status == 423 => {
                let detail = response.body.get("detail").cloned().unwrap_or(Value::Null);
                self.banned_until = detail.get("until").and_then(Value::as_str).unwrap_or("时间未知").to_string();
                self.ban_reason = detail.get("reason").and_then(Value::as_str).unwrap_or("未填写原因").to_string();
                self.mode = Mode::Banned;
                self.status.clear();
            }''',
        '''            Ok(response) if response.status == 423 => {
                let detail = response.body.get("detail").cloned().unwrap_or(Value::Null);
                self.banned_until = detail.get("until").and_then(Value::as_str).unwrap_or("时间未知").to_string();
                self.ban_reason = detail.get("reason").and_then(Value::as_str).unwrap_or("未填写原因").to_string();
                self.persist_ban(config);
                self.mode = Mode::Banned;
                self.status.clear();
            }''',
        "persist server ban state locally",
    )
    source = replace_once(
        source,
        '''            Ok(response) if !(200..300).contains(&response.status) => {
                let detail = response.body.get("detail").and_then(Value::as_str)
                    .or_else(|| response.body.get("detail").and_then(|v| v.get("message")).and_then(Value::as_str))
                    .unwrap_or("请求失败");
                self.status = format!("{detail}（HTTP {}）", response.status);
                if matches!(action, Action::Verify) {
                    self.mode = Mode::Unavailable;
                }
            }''',
        '''            Ok(response) if !(200..300).contains(&response.status) => {
                let detail = response.body.get("detail").and_then(Value::as_str)
                    .or_else(|| response.body.get("detail").and_then(|v| v.get("message")).and_then(Value::as_str))
                    .unwrap_or("请求失败");
                self.status = format!("{detail}（HTTP {}）", response.status);
                if matches!(action, Action::Whitelist) {
                    if self.whitelist_ready {
                        self.status = "白名单更新失败，当前使用上次下载的本地白名单。".to_string();
                        if self.token.is_some() {
                            self.mode = Mode::Checking;
                            self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
                        } else {
                            self.mode = Mode::Auth;
                        }
                    } else {
                        self.mode = Mode::Unavailable;
                    }
                } else if matches!(action, Action::Verify) {
                    self.mode = Mode::Unavailable;
                }
            }''',
        "handle failed whitelist refresh with cache fallback",
    )
    source = replace_once(
        source,
        '''            Ok(response) => match action {
                Action::Verify => {''',
        '''            Ok(response) => match action {
                Action::Whitelist => {
                    let revision = response.body.get("revision").and_then(Value::as_str).unwrap_or("").to_string();
                    let qq_hashes = response.body.get("qq_hashes").and_then(Value::as_array)
                        .map(|items| items.iter().filter_map(Value::as_str).map(str::to_string).collect())
                        .unwrap_or_default();
                    let wechat_hashes = response.body.get("wechat_hashes").and_then(Value::as_array)
                        .map(|items| items.iter().filter_map(Value::as_str).map(str::to_string).collect())
                        .unwrap_or_default();
                    if revision.is_empty() {
                        self.status = "服务器返回的白名单版本信息不完整。".to_string();
                        self.mode = Mode::Unavailable;
                    } else {
                        self.whitelist = SavedWhitelist { revision, qq_hashes, wechat_hashes };
                        self.whitelist_ready = true;
                        if let Some(store) = config {
                            if let Ok(data) = serde_json::to_string(&self.whitelist) {
                                let _ = store.write("effectcraft-account-whitelist.json", &data);
                            }
                        }
                        self.status.clear();
                        if self.token.is_some() {
                            self.mode = Mode::Checking;
                            self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
                        } else {
                            self.mode = Mode::Auth;
                        }
                    }
                }
                Action::Verify => {''',
        "handle successful whitelist download",
    )
    source = replace_once(
        source,
        '''                        self.user = Some(user);
                        self.mode = Mode::Editor;
                        self.status.clear();
                        self.persist(config);''',
        '''                        self.user = Some(user);
                        self.mode = Mode::Editor;
                        self.status.clear();
                        self.clear_cached_ban(config);
                        self.persist(config);''',
        "clear cached ban after verified account",
    )
    source = replace_once(
        source,
        '''                        self.token = Some(token);
                        self.user = user;
                        self.mode = Mode::Success;
                        self.password.clear();
                        self.persist(config);''',
        '''                        self.token = Some(token);
                        self.user = user;
                        self.mode = Mode::Success;
                        self.password.clear();
                        self.clear_cached_ban(config);
                        self.persist(config);''',
        "clear cached ban after successful login",
    )

    source = replace_once(
        source,
        '''            ui.horizontal(|ui| {
                if ui.selectable_label(!app.account.login_mode_register, "登录").clicked() {''',
        '''            if app.account.whitelist_ready {
                ui.label(format!(
                    "本机白名单已下载：QQ {} 条，微信 {} 条",
                    app.account.whitelist.qq_hashes.len(),
                    app.account.whitelist.wechat_hashes.len()
                ));
            } else {
                ui.label("正在下载白名单；下载完成前不能注册或登录。");
            }
            ui.horizontal(|ui| {
                if ui.selectable_label(!app.account.login_mode_register, "登录").clicked() {''',
        "show local whitelist state",
    )
    source = replace_once(
        source,
        '''            ui.add_space(8.0);
            let busy = app.account.pending.is_some();''',
        '''            ui.add_space(8.0);
            let busy = app.account.pending.is_some() || !app.account.whitelist_ready;''',
        "disable submit until whitelist is ready",
    )
    source = replace_once(
        source,
        '''                ui.label(&app.account.ban_reason);
                ui.add_space(18.0);
                if ui.button("OK").clicked() {
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }''',
        '''                ui.label(&app.account.ban_reason);
                ui.add_space(8.0);
                ui.label(app.account.ban_countdown_label());
                ui.add_space(12.0);
                if ui.button("联网核验是否已解封").clicked() {
                    app.account.retry(config);
                }
                if ui.button("OK").clicked() {
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }''',
        "show offline cached ban state",
    )

    account_path.write_text(source, encoding="utf-8")

    # Add SHA-256 to the shared dependency graph; the UI crate uses it to compare
    # locally cached hashes without storing the complete QQ/WeChat list in plaintext.
    workspace_path = root / "Cargo.toml"
    workspace = workspace_path.read_text(encoding="utf-8")
    if 'sha2 = "0.10"' not in workspace:
        anchor = 'serde_json = { version = "1", features = ["float_roundtrip"] }\n'
        if workspace.count(anchor) != 1:
            raise SystemExit("Cannot add sha2 workspace dependency: serde_json anchor not unique")
        workspace_path.write_text(workspace.replace(anchor, anchor + 'sha2 = "0.10"\n', 1), encoding="utf-8")
    ui_path = root / "crates/ui-egui/Cargo.toml"
    ui = ui_path.read_text(encoding="utf-8")
    if 'sha2 = { workspace = true }' not in ui:
        # serde_json also appears under [build-dependencies] in this crate.
        # Add sha2 specifically to the normal [dependencies] table.
        dependency_header = "[dependencies]\n"
        if ui.count(dependency_header) != 1:
            raise SystemExit("Cannot add sha2 UI dependency: [dependencies] table is not unique")
        insertion = ui.index(dependency_header) + len(dependency_header)
        ui = ui[:insertion] + 'sha2 = { workspace = true }\n' + ui[insertion:]
        ui_path.write_text(ui, encoding="utf-8")

    print("Added local hashed QQ/WeChat whitelist checks, local startup refresh and offline-persisted ban state.")
    print("Cloudflare remains authoritative and still checks registration, login, session and profile requests.")


if __name__ == "__main__":
    main()
