#!/usr/bin/env python3
"""Add offline-first local registration and on-demand retry to the EffectCraft account gate."""
from __future__ import annotations

from pathlib import Path
import os

def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return source.replace(old, new, 1)

def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"])
    path = root / "crates/ui-egui/src/account.rs"
    if not path.is_file():
        raise SystemExit("Run add_home_lan_account_gate.py before this patch.")

    source = path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        """#[derive(Serialize, Deserialize)]
struct SavedAccount {
    server_url: String,
    token: String,
}

struct HttpResult {""",
        """#[derive(Serialize, Deserialize)]
struct SavedAccount {
    server_url: String,
    token: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct PendingRegistration {
    #[serde(default)]
    server_url: String,
    #[serde(default)]
    user: User,
    #[serde(default)]
    created_at: String,
}

struct HttpResult {""",
        "pending registration record",
    )

    source = replace_once(
        source,
        """    pending: Option<Receiver<Result<HttpResult, String>>>,
    pending_action: Option<Action>,
    events: Option<Receiver<Value>>,
}""",
        """    pending: Option<Receiver<Result<HttpResult, String>>>,
    pending_action: Option<Action>,
    events: Option<Receiver<Value>>,
    pending_registration: Option<PendingRegistration>,
    local_only: bool,
    next_sync_at: Option<std::time::Instant>,
    sync_retry_secs: u64,
}""",
        "account state offline sync fields",
    )

    source = replace_once(
        source,
        """            pending: None,
            pending_action: None,
            events: None,
        }""",
        """            pending: None,
            pending_action: None,
            events: None,
            pending_registration: None,
            local_only: false,
            next_sync_at: None,
            sync_retry_secs: 0,
        }""",
        "account state offline sync defaults",
    )

    source = replace_once(
        source,
        """        if self.token.is_some() {
            self.mode = Mode::Checking;
            self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
        } else {
            self.mode = Mode::Auth;
        }""",
        """        if self.token.is_some() {
            self.mode = Mode::Checking;
            self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
        } else if let Some(data) = config.and_then(|store| store.read("effectcraft-home-pending-registration.json")) {
            match serde_json::from_str::<PendingRegistration>(&data) {
                Ok(pending) => {
                    if !pending.server_url.is_empty() {
                        self.server_url = pending.server_url.clone();
                    }
                    self.user = Some(pending.user.clone());
                    self.pending_registration = Some(pending);
                    self.local_only = true;
                    self.mode = Mode::Editor;
                    self.status = "本地账号已保存，尚未同步到管理员账号节点。请打开“账号信息”输入密码完成同步。".to_string();
                }
                Err(error) => {
                    self.mode = Mode::Auth;
                    self.status = format!("本地待同步账号资料无法读取：{error}");
                }
            }
        } else {
            self.mode = Mode::Auth;
        }""",
        "load pending local account after saved login",
    )

    source = replace_once(
        source,
        """    fn remove_saved(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if let Some(store) = config {
            let _ = store.remove("effectcraft-home-account.json");
        }
    }""",
        """    fn remove_saved(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if let Some(store) = config {
            let _ = store.remove("effectcraft-home-account.json");
        }
    }

    fn persist_pending_registration(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let (Some(store), Some(pending)) = (config, self.pending_registration.as_ref()) else {
            return;
        };
        if let Ok(data) = serde_json::to_string(pending) {
            let _ = store.write("effectcraft-home-pending-registration.json", &data);
        }
    }

    fn remove_pending_registration(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if let Some(store) = config {
            let _ = store.remove("effectcraft-home-pending-registration.json");
        }
    }

    fn create_local_registration(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let qq = self.qq.trim();
        let wechat = self.wechat.trim();
        let qq_valid = qq.is_empty() || (qq.len() >= 5 && qq.len() <= 12 && qq.as_bytes()[0].is_ascii_digit() && qq.as_bytes()[0] != b'0' && qq.bytes().all(|c| c.is_ascii_digit()));
        let wechat_valid = wechat.is_empty() || (wechat.len() >= 6 && wechat.len() <= 32 && wechat.as_bytes()[0].is_ascii_alphabetic() && wechat.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-'));
        if (qq.is_empty() && wechat.is_empty()) || !qq_valid || !wechat_valid {
            self.status = "离线注册失败：QQ号和微信号至少填写一项；已填写的号码必须符合格式。".to_string();
            self.mode = Mode::Auth;
            return;
        }
        if self.name.trim().is_empty() || self.name.trim().chars().count() > 40 || self.password.chars().count() < 8 || self.password.chars().count() > 128 {
            self.status = "离线注册失败：请填写昵称，并设置8至128位密码。".to_string();
            self.mode = Mode::Auth;
            return;
        }
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let user = User {
            id: format!("local-{now}"),
            qq: self.qq.trim().to_string(),
            wechat: self.wechat.trim().to_string(),
            name: self.name.trim().to_string(),
            avatar_url: self.avatar_url.trim().to_string(),
            created_at: format!("{now}"),
            banned_until: None,
            ban_reason: String::new(),
        };
        self.pending_registration = Some(PendingRegistration {
            server_url: self.server_url.clone(),
            user: user.clone(),
            created_at: format!("{now}"),
        });
        self.user = Some(user);
        self.local_only = true;
        self.mode = Mode::Editor;
        self.status = "本地注册成功，账号资料已保存在本机；尚未同步到管理员账号节点。保持应用运行，网络恢复后会自动重试。为保护密码，密码仅保留在当前运行内存；重启应用后需重新输入密码同步。".to_string();
        self.persist_pending_registration(config);
        self.schedule_registration_retry();
    }

    fn schedule_registration_retry(&mut self) {
        // Offline registration is the only automatic retry. Start gently and back off
        // to at most one sync attempt per hour while the phone remains offline.
        let delay = if self.sync_retry_secs == 0 { 60 } else { self.sync_retry_secs };
        self.next_sync_at = Some(std::time::Instant::now() + std::time::Duration::from_secs(delay));
        self.sync_retry_secs = (delay.saturating_mul(2)).min(3600);
    }

    fn submit_pending_registration(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let Some(pending) = self.pending_registration.as_ref() else {
            self.status = "没有待同步的本地账号".to_string();
            return;
        };
        if self.password.is_empty() {
            self.status = "请输入注册时设置的密码，然后同步本地账号".to_string();
            return;
        }
        let user = pending.user.clone();
        self.qq = user.qq;
        self.wechat = user.wechat;
        self.name = user.name;
        self.avatar_url = user.avatar_url;
        self.next_sync_at = None;
        self.send(
            Action::Register,
            "POST",
            "/v1/register",
            json!({
                "qq": self.qq.trim(),
                "wechat": self.wechat.trim(),
                "name": self.name.trim(),
                "password": self.password,
                "avatar_url": self.avatar_url.trim()
            }),
            config,
        );
    }

    fn maybe_retry_pending_registration(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if !self.local_only || self.pending_registration.is_none() || self.password.is_empty() || self.pending.is_some() {
            return;
        }
        let due = self.next_sync_at.map(|when| std::time::Instant::now() >= when).unwrap_or(false);
        if due {
            self.submit_pending_registration(config);
        }
    }

    fn send(&mut self,""",
        "pending registration persistence and retry methods",
    )

    source = replace_once(
        source,
        """    fn submit_profile(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        self.send(""",
        """    fn submit_profile(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if self.local_only {
            let qq = self.edit_qq.trim().to_string();
            let wechat = self.edit_wechat.trim().to_string();
            let name = self.edit_name.trim().to_string();
            let avatar = self.edit_avatar.trim().to_string();
            let server_url = self.server_url.clone();
            let new_password = self.new_password.clone();
            if qq.is_empty() && wechat.is_empty() {
                self.status = "QQ号和微信号至少填写一项".to_string();
                return;
            }
            if !new_password.is_empty() && (new_password.chars().count() < 8 || new_password.chars().count() > 128) {
                self.status = "新密码必须为8至128位".to_string();
                return;
            }
            let Some(pending) = self.pending_registration.as_mut() else {
                self.status = "本地待同步账号资料不存在".to_string();
                return;
            };
            pending.user.qq = qq;
            pending.user.wechat = wechat;
            pending.user.name = name;
            pending.user.avatar_url = avatar;
            pending.server_url = server_url;
            let updated = pending.user.clone();
            self.user = Some(updated);
            if !new_password.is_empty() {
                self.password = new_password;
            }
            self.current_password.clear();
            self.new_password.clear();
            self.persist_pending_registration(config);
            self.status = "本地账号资料已更新，仍待管理员节点同步。".to_string();
            return;
        }
        self.send(""",
        "save local-only profile changes without a server request",
    )

    source = replace_once(
        source,
        """            Err(error) => {
                self.status = format!("无法连接家中的账号服务器：{error}");
                if matches!(action, Action::Verify) {
                    self.mode = Mode::Unavailable;
                }
            }""",
        """            Err(error) => {
                if matches!(action, Action::Register) {
                    if self.pending_registration.is_none() {
                        self.create_local_registration(config);
                    } else {
                        self.status = format!("本地账号仍待同步：{error}。网络恢复后会自动重试。");
                        self.schedule_registration_retry();
                    }
                } else {
                    self.status = format!("无法连接管理员账号节点：{error}");
                    if matches!(action, Action::Verify) {
                        self.mode = Mode::Unavailable;
                    }
                }
            }""",
        "offline registration fallback",
    )

    source = replace_once(
        source,
        """            Ok(response) if !(200..300).contains(&response.status) => {
                let detail = response.body.get("detail").and_then(Value::as_str)
                    .or_else(|| response.body.get("detail").and_then(|v| v.get("message")).and_then(Value::as_str))
                    .unwrap_or("请求失败");
                self.status = format!("{detail}（HTTP {}）", response.status);
                if matches!(action, Action::Verify) {
                    self.mode = Mode::Unavailable;
                }
            }""",
        """            Ok(response) if !(200..300).contains(&response.status) => {
                let detail = response.body.get("detail").and_then(Value::as_str)
                    .or_else(|| response.body.get("detail").and_then(|v| v.get("message")).and_then(Value::as_str))
                    .unwrap_or("请求失败");
                if matches!(action, Action::Register) && response.status >= 500 {
                    if self.pending_registration.is_none() {
                        self.create_local_registration(config);
                    } else {
                        self.status = format!("本地账号仍待同步：服务器暂时不可用（HTTP {}）。稍后自动重试。", response.status);
                        self.schedule_registration_retry();
                    }
                } else if matches!(action, Action::Register) && response.status == 409 {
                    self.next_sync_at = None;
                    self.status = "账号标识发生冲突：QQ号或微信号可能已经注册。为避免覆盖原账号，已暂停自动同步；请使用已有账号登录，或修改本地资料后再处理。".to_string();
                    self.mode = if self.pending_registration.is_some() { Mode::Editor } else { Mode::Auth };
                } else {
                    self.status = format!("{detail}（HTTP {}）", response.status);
                    if matches!(action, Action::Verify) {
                        self.mode = Mode::Unavailable;
                    }
                }
            }""",
        "offline server failure and duplicate handling",
    )

    source = replace_once(
        source,
        """                        self.token = Some(token);
                        self.user = user;
                        self.mode = Mode::Success;
                        self.password.clear();
                        self.persist(config);""",
        """                        self.token = Some(token);
                        self.user = user;
                        self.mode = Mode::Success;
                        self.password.clear();
                        self.local_only = false;
                        self.pending_registration = None;
                        self.next_sync_at = None;
                        self.sync_retry_secs = 0;
                        self.remove_pending_registration(config);
                        self.persist(config);""",
        "clear pending registration after server success",
    )

    source = replace_once(
        source,
        """    app.account.ensure_loaded(config);
    app.account.poll(config);""",
        """    app.account.ensure_loaded(config);
    app.account.poll(config);
    app.account.maybe_retry_pending_registration(config);""",
        "run pending sync retry without periodic account verification",
    )

    source = replace_once(
        source,
        """                    if ui.button("账号信息").clicked() {""",
        """                    let account_label = if app.account.local_only { "本地账号 · 待同步" } else { "账号信息" };
                    if ui.button(account_label).clicked() {""",
        "visible pending account label",
    )

    source = replace_once(
        source,
        """                    ui.label("修改密码（不修改可留空）");""",
        """                    if app.account.local_only {
                        ui.separator();
                        ui.colored_label(Color32::from_rgb(220, 150, 40), "本地注册完成 · 待同步到管理员账号节点");
                        ui.label("管理员节点 ID（p2p://…）");
                        ui.text_edit_singleline(&mut app.account.server_url);
                        ui.label("重新输入注册密码以同步（密码不会写入本地账号文件）");
                        ui.add(egui::TextEdit::singleline(&mut app.account.password).password(true));
                        let can_sync = app.account.pending.is_none() && !app.account.password.is_empty();
                        if ui.add_enabled(can_sync, egui::Button::new("立即同步本地账号")).clicked() {
                            app.account.submit_pending_registration(config);
                        }
                        ui.small("应用保持运行时会自动重试；若退出后再打开，为保护密码需要重新输入一次。服务器检测到 QQ/微信重复时不会覆盖已有账号。");
                    }
                    ui.label("修改密码（不修改可留空）");""",
        "pending local account sync controls",
    )

    # Version marker protects repeated local rebuilds and makes CI intent auditable.
    marker = "// EFFECTCRAFT_OFFLINE_LOCAL_REGISTRATION_V1"
    if marker not in source:
        source = source.replace("// EFFECTCRAFT_HOME_LAN_ACCOUNT_GATE_V1", "// EFFECTCRAFT_HOME_LAN_ACCOUNT_GATE_V1\n" + marker, 1)

    path.write_text(source, encoding="utf-8")
    print("Added offline-first registration, explicit pending-sync state, duplicate protection, and backoff retries (no 10-second validation polling).")

if __name__ == "__main__":
    main()
