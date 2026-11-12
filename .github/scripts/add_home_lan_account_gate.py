#!/usr/bin/env python3
"""Install a first-launch home-LAN account gate into the shared EffectCraft egui app."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_HOME_LAN_ACCOUNT_GATE_V1"

ACCOUNT_RS = r'''// EFFECTCRAFT_HOME_LAN_ACCOUNT_GATE_V1
//! Home-Wi-Fi-only account gate. The account API is intentionally fail-closed:
//! when a saved account cannot be checked against the home server, the editor stays locked.
use crate::EffectcraftApp;
use egui::{Align2, Color32, Id, Order, Sense, Stroke, StrokeKind, Vec2, pos2, vec2};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::time::Duration;

const DEFAULT_SERVER: &str = "p2p://auto";

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum Mode {
    #[default]
    Auth,
    Checking,
    Unavailable,
    Success,
    Banned,
    Editor,
}

#[derive(Clone, Copy, Debug)]
enum Action {
    Verify,
    Login,
    Register,
    Profile,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct User {
    #[serde(default)]
    id: String,
    #[serde(default)]
    qq: String,
    #[serde(default)]
    wechat: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    avatar_url: String,
    #[serde(default)]
    created_at: String,
    #[serde(default)]
    banned_until: Option<String>,
    #[serde(default)]
    ban_reason: String,
}

#[derive(Serialize, Deserialize)]
struct SavedAccount {
    server_url: String,
    token: String,
}

struct HttpResult {
    status: u16,
    body: Value,
}

pub(crate) struct AccountState {
    loaded: bool,
    mode: Mode,
    pub(crate) server_url: String,
    token: Option<String>,
    user: Option<User>,
    login_mode_register: bool,
    login_identifier: String,
    qq: String,
    wechat: String,
    name: String,
    password: String,
    avatar_url: String,
    edit_open: bool,
    edit_qq: String,
    edit_wechat: String,
    edit_name: String,
    edit_avatar: String,
    current_password: String,
    new_password: String,
    banned_until: String,
    ban_reason: String,
    status: String,
    pending: Option<Receiver<Result<HttpResult, String>>>,
    pending_action: Option<Action>,
    last_verified: Option<std::time::Instant>,
}

impl Default for AccountState {
    fn default() -> Self {
        Self {
            loaded: false,
            mode: Mode::Auth,
            server_url: DEFAULT_SERVER.to_string(),
            token: None,
            user: None,
            login_mode_register: false,
            login_identifier: String::new(),
            qq: String::new(),
            wechat: String::new(),
            name: String::new(),
            password: String::new(),
            avatar_url: String::new(),
            edit_open: false,
            edit_qq: String::new(),
            edit_wechat: String::new(),
            edit_name: String::new(),
            edit_avatar: String::new(),
            current_password: String::new(),
            new_password: String::new(),
            banned_until: String::new(),
            ban_reason: String::new(),
            status: String::new(),
            pending: None,
            pending_action: None,
            last_verified: None,
        }
    }
}

impl AccountState {
    fn account_file(config: Option<&dyn effectcraft_engine::config::ConfigStore>) -> Option<&'static str> {
        config.map(|_| "effectcraft-home-account.json")
    }

    fn ensure_loaded(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if self.loaded {
            return;
        }
        self.loaded = true;
        if let Some(name) = Self::account_file(config) {
            if let Some(data) = config.and_then(|store| store.read(name)) {
                if let Ok(saved) = serde_json::from_str::<SavedAccount>(&data) {
                    // Preserve an explicitly pinned administrator identity. Upgrade
                    // legacy LAN profiles to auto-discovery without discarding tokens.
                    self.server_url = if saved.server_url.starts_with("p2p://") {
                        saved.server_url
                    } else {
                        DEFAULT_SERVER.to_string()
                    };
                    if !saved.token.is_empty() {
                        self.token = Some(saved.token);
                    }
                }
            }
        }
        if self.token.is_some() {
            self.mode = Mode::Checking;
            self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
        } else {
            self.mode = Mode::Auth;
        }
    }

    fn persist(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let (Some(store), Some(token)) = (config, self.token.as_ref()) else {
            return;
        };
        let saved = SavedAccount { server_url: self.server_url.clone(), token: token.clone() };
        if let Ok(data) = serde_json::to_string(&saved) {
            let _ = store.write("effectcraft-home-account.json", &data);
        }
    }

    fn remove_saved(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        if let Some(store) = config {
            let _ = store.remove("effectcraft-home-account.json");
        }
    }

    fn send(&mut self, action: Action, method: &str, path: &str, body: Value, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let url = self.server_url.trim().trim_end_matches('/').to_string();
        let method = method.to_string();
        let path = path.to_string();
        let token = self.token.clone();
        let (tx, rx) = mpsc::channel();
        self.pending = Some(rx);
        self.pending_action = Some(action);
        self.status = "正在连接管理员账号节点…".to_string();
        std::thread::spawn(move || {
            let _ = tx.send(http_request(&url, &method, &path, body, token.as_deref()));
        });
        let _ = config;
    }

    fn submit_login(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        self.send(
            Action::Login,
            "POST",
            "/v1/login",
            json!({"identifier": self.login_identifier.trim(), "password": self.password}),
            config,
        );
    }

    fn submit_register(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
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

    fn submit_profile(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        self.send(
            Action::Profile,
            "POST",
            "/v1/profile",
            json!({
                "qq": self.edit_qq.trim(),
                "wechat": self.edit_wechat.trim(),
                "name": self.edit_name.trim(),
                "avatar_url": self.edit_avatar.trim(),
                "current_password": self.current_password,
                "new_password": self.new_password
            }),
            config,
        );
    }

    fn poll(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let received = match self.pending.as_ref().map(|rx| rx.try_recv()) {
            Some(Ok(result)) => Some(result),
            Some(Err(TryRecvError::Disconnected)) => Some(Err("账号网络请求已中断".to_string())),
            Some(Err(TryRecvError::Empty)) | None => None,
        };
        let Some(result) = received else { return; };
        self.pending = None;
        let action = self.pending_action.take().unwrap_or(Action::Verify);
        match result {
            Err(error) => {
                self.status = format!("无法连接家中的账号服务器：{error}");
                if matches!(action, Action::Verify) {
                    self.mode = Mode::Unavailable;
                }
            }
            Ok(response) if response.status == 423 => {
                let detail = response.body.get("detail").cloned().unwrap_or(Value::Null);
                self.banned_until = detail.get("until").and_then(Value::as_str).unwrap_or("时间未知").to_string();
                self.ban_reason = detail.get("reason").and_then(Value::as_str).unwrap_or("未填写原因").to_string();
                self.mode = Mode::Banned;
                self.status.clear();
            }
            Ok(response) if !(200..300).contains(&response.status) => {
                let detail = response.body.get("detail").and_then(Value::as_str)
                    .or_else(|| response.body.get("detail").and_then(|v| v.get("message")).and_then(Value::as_str))
                    .unwrap_or("请求失败");
                self.status = format!("{detail}（HTTP {}）", response.status);
                if matches!(action, Action::Verify) {
                    self.mode = Mode::Unavailable;
                }
            }
            Ok(response) => match action {
                Action::Verify => {
                    if let Some(user) = response.body.get("user").cloned().and_then(|v| serde_json::from_value::<User>(v).ok()) {
                        self.user = Some(user);
                        self.mode = Mode::Editor;
                        self.last_verified = Some(std::time::Instant::now());
                        self.status.clear();
                        self.persist(config);
                    } else {
                        self.mode = Mode::Unavailable;
                        self.status = "服务器返回的账号资料格式不正确".to_string();
                    }
                }
                Action::Login | Action::Register => {
                    let token = response.body.get("token").and_then(Value::as_str).unwrap_or("").to_string();
                    let user = response.body.get("user").cloned().and_then(|v| serde_json::from_value::<User>(v).ok());
                    if token.is_empty() || user.is_none() {
                        self.status = "服务器返回的登录数据不完整".to_string();
                        self.mode = Mode::Auth;
                    } else {
                        self.token = Some(token);
                        self.user = user;
                        self.mode = Mode::Success;
                        self.password.clear();
                        self.persist(config);
                    }
                }
                Action::Profile => {
                    if let Some(user) = response.body.get("user").cloned().and_then(|v| serde_json::from_value::<User>(v).ok()) {
                        self.user = Some(user);
                        self.edit_open = false;
                        self.current_password.clear();
                        self.new_password.clear();
                        self.status = "账号资料已更新".to_string();
                        self.persist(config);
                    } else {
                        self.status = "资料更新后未收到有效账号信息".to_string();
                    }
                }
            },
        }
    }

    fn retry(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        self.status.clear();
        if self.token.is_some() {
            // Save a changed administrator address before verifying the existing token,
            // so an upgraded LAN account can complete its one-time P2P identity pairing.
            self.persist(config);
            self.mode = Mode::Checking;
            self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
        } else {
            self.mode = Mode::Auth;
        }
    }
}

fn http_request(url: &str, method: &str, path: &str, body: Value, token: Option<&str>) -> Result<HttpResult, String> {
    if url.starts_with("p2p://") {
        return p2p_account_request(url, method, path, body, token);
    }
    let rest = url.strip_prefix("http://").ok_or_else(|| "服务器连接方式无效，请使用 p2p://auto 或家庭局域网 http:// 地址".to_string())?;
    let authority = rest.split('/').next().unwrap_or("");
    let (host, port) = authority.rsplit_once(':').unwrap_or((authority, "80"));
    if host.is_empty() || host.contains(' ') {
        return Err("服务器地址不正确，请填写家中电脑的局域网IPv4地址和端口".to_string());
    }
    let port: u16 = port.parse().map_err(|_| "服务器端口不正确".to_string())?;
    let address = (host, port).to_socket_addrs().map_err(|e| e.to_string())?
        .next().ok_or_else(|| "无法解析服务器地址".to_string())?;
    let is_home_lan = match address.ip() {
        std::net::IpAddr::V4(ip) => ip.is_private() || ip.is_loopback() || ip.is_link_local(),
        std::net::IpAddr::V6(ip) => ip.is_loopback() || ip.is_unique_local() || ip.is_unicast_link_local(),
    };
    if !is_home_lan {
        return Err("账号服务器地址必须是家庭局域网 IP，不能使用公网地址".to_string());
    }
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(7)).map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(8))).map_err(|e| e.to_string())?;
    stream.set_write_timeout(Some(Duration::from_secs(8))).map_err(|e| e.to_string())?;
    let body_bytes = if body.is_null() { Vec::new() } else { serde_json::to_vec(&body).map_err(|e| e.to_string())? };
    let mut request = format!(
        "{method} {path} HTTP/1.1\r\nHost: {authority}\r\nAccept: application/json\r\nConnection: close\r\n"
    );
    if !body_bytes.is_empty() {
        request.push_str("Content-Type: application/json\r\n");
        request.push_str(&format!("Content-Length: {}\r\n", body_bytes.len()));
    }
    if let Some(token) = token {
        request.push_str(&format!("Authorization: Bearer {token}\r\n"));
    }
    request.push_str("\r\n");
    stream.write_all(request.as_bytes()).map_err(|e| e.to_string())?;
    if !body_bytes.is_empty() {
        stream.write_all(&body_bytes).map_err(|e| e.to_string())?;
    }
    let mut bytes = Vec::new();
    stream.read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    let text = String::from_utf8_lossy(&bytes);
    let (headers, response_body) = text.split_once("\r\n\r\n").ok_or_else(|| "服务器响应不完整".to_string())?;
    let status = headers.lines().next().and_then(|line| line.split_whitespace().nth(1))
        .and_then(|code| code.parse::<u16>().ok()).ok_or_else(|| "服务器响应状态码无效".to_string())?;
    let value = serde_json::from_str::<Value>(response_body).unwrap_or_else(|_| json!({"detail": "服务器返回了无法识别的数据"}));
    Ok(HttpResult { status, body: value })
}


fn p2p_account_request(url: &str, method: &str, path: &str, body: Value, token: Option<&str>) -> Result<HttpResult, String> {
    let peer_spec = url.strip_prefix("p2p://").unwrap_or("auto");
    if peer_spec.is_empty() || peer_spec == "auto" {
        return Err("已完成自动发现入口，但为保护账号密码，必须先填写管理员管理版复制的 p2p://节点ID；固定后以后会自动连接，不会每次审批。".to_string());
    }
    if peer_spec.len() < 30 || peer_spec.len() > 120
        || !peer_spec.bytes().all(|c| c.is_ascii_alphanumeric())
    {
        return Err("管理员节点 ID 不正确。请填写 p2p:// 后接管理版复制的完整节点 ID。".to_string());
    }
    let preferred_peer_id = peer_spec.to_string();
    let address = "127.0.0.1:8789".parse::<std::net::SocketAddr>().map_err(|e| e.to_string())?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(5))
        .map_err(|_| "P2P 账号通道尚未就绪，请确认管理员手机已启动账号管理版并保持在线".to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(40))).map_err(|e| e.to_string())?;
    stream.set_write_timeout(Some(Duration::from_secs(5))).map_err(|e| e.to_string())?;
    let body_text = if body.is_null() { String::new() } else { serde_json::to_string(&body).map_err(|e| e.to_string())? };
    let packet = json!({
        "method": method,
        "path": path,
        "token": token.unwrap_or(""),
        "preferred_peer_id": preferred_peer_id,
        "body": body_text
    });
    let wire = serde_json::to_vec(&packet).map_err(|e| e.to_string())?;
    stream.write_all(&wire).map_err(|e| e.to_string())?;
    stream.write_all(b"\n").map_err(|e| e.to_string())?;
    stream.flush().map_err(|e| e.to_string())?;
    let mut bytes = Vec::new();
    stream.read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    let envelope: Value = serde_json::from_slice(&bytes).map_err(|e| format!("P2P 账号通道响应格式错误：{e}"))?;
    let status = envelope.get("status").and_then(Value::as_u64).unwrap_or(503) as u16;
    let raw_body = envelope.get("body").and_then(Value::as_str).unwrap_or("{\"detail\":\"P2P 账号服务器未返回数据\"}");
    let response_body = serde_json::from_str::<Value>(raw_body).unwrap_or_else(|_| json!({"detail": "P2P 账号服务器返回了无法识别的数据"}));
    Ok(HttpResult { status, body: response_body })
}

fn blocking_overlay(ctx: &egui::Context) {
    let screen = ctx.content_rect();
    egui::Area::new(Id::new("effectcraft-account-blocking-overlay"))
        .order(Order::Foreground)
        .fixed_pos(screen.min)
        .show(ctx, |ui| {
            ui.set_min_size(screen.size());
            let (rect, _) = ui.allocate_exact_size(screen.size(), Sense::click_and_drag());
            ui.painter().rect_filled(rect, 0.0, Color32::from_rgba_unmultiplied(8, 11, 18, 242));
        });
}

fn centered_window(ctx: &egui::Context, title: &str, size: Vec2, add_contents: impl FnOnce(&mut egui::Ui)) {
    let screen = ctx.content_rect();
    let size = vec2(size.x.min((screen.width() - 24.0).max(260.0)), size.y.min((screen.height() - 24.0).max(260.0)));
    egui::Window::new(title)
        .id(Id::new(("effectcraft-account-window", title)))
        .order(Order::Foreground)
        .fixed_pos(pos2(screen.center().x - size.x * 0.5, screen.center().y - size.y * 0.5))
        .fixed_size(size)
        .movable(false)
        .collapsible(false)
        .resizable(false)
        .show(ctx, add_contents);
}

pub(crate) fn show(app: &mut EffectcraftApp, ctx: &egui::Context) {
    let config = app.session.config.clone();
    let config = config.as_deref();
    app.account.ensure_loaded(config);
    app.account.poll(config);
    if app.account.mode == Mode::Editor
        && app.account.pending.is_none()
        && app.account.last_verified.map_or(true, |last| last.elapsed() > std::time::Duration::from_secs(10))
    {
        app.account.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
    }

    if app.account.mode == Mode::Editor {
        if app.ui.start_screen {
            egui::Area::new(Id::new("effectcraft-home-account-button"))
                .order(Order::Foreground)
                .anchor(Align2::RIGHT_TOP, vec2(-12.0, 12.0))
                .show(ctx, |ui| {
                    if ui.button("账号信息").clicked() {
                        if let Some(user) = app.account.user.as_ref() {
                            app.account.edit_qq = user.qq.clone();
                            app.account.edit_wechat = user.wechat.clone();
                            app.account.edit_name = user.name.clone();
                            app.account.edit_avatar = user.avatar_url.clone();
                            app.account.edit_open = true;
                        }
                    }
                });
        } else {
            app.account.edit_open = false;
        }

        if app.account.edit_open && app.ui.start_screen {
            egui::Window::new("账号信息")
                .id(Id::new("effectcraft-account-profile-window"))
                .order(Order::Foreground)
                .default_pos(ctx.content_rect().center() - vec2(190.0, 230.0))
                .default_size((380.0, 460.0))
                .movable(true)
                .collapsible(false)
                .resizable(false)
                .show(ctx, |ui| {
                    ui.label("QQ号");
                    ui.text_edit_singleline(&mut app.account.edit_qq);
                    ui.label("微信号");
                    ui.text_edit_singleline(&mut app.account.edit_wechat);
                    ui.label("名字");
                    ui.text_edit_singleline(&mut app.account.edit_name);
                    ui.label("头像图片地址（可填写 https 图片链接）");
                    ui.text_edit_singleline(&mut app.account.edit_avatar);
                    ui.separator();
                    ui.label("修改密码（不修改可留空）");
                    ui.label("当前密码");
                    ui.add(egui::TextEdit::singleline(&mut app.account.current_password).password(true));
                    ui.label("新密码");
                    ui.add(egui::TextEdit::singleline(&mut app.account.new_password).password(true));
                    ui.separator();
                    ui.horizontal(|ui| {
                        let busy = app.account.pending.is_some();
                        if ui.add_enabled(!busy, egui::Button::new("保存资料")).clicked() {
                            app.account.submit_profile(config);
                        }
                        if ui.button("关闭").clicked() {
                            app.account.edit_open = false;
                        }
                        if ui.button("退出账号").clicked() {
                            app.account.token = None;
                            app.account.user = None;
                            app.account.edit_open = false;
                            app.account.mode = Mode::Auth;
                            app.account.remove_saved(config);
                        }
                    });
                    if !app.account.status.is_empty() {
                        ui.label(&app.account.status);
                    }
                });
        }
        return;
    }

    blocking_overlay(ctx);
    match app.account.mode {
        Mode::Auth => centered_window(ctx, "账号注册 / 登录", vec2(420.0, 570.0), |ui| {
            ui.vertical_centered(|ui| {
                ui.heading("EffectCraft 账号");
                ui.label("通过 P2P 自动连接管理员手机账号节点");
            });
            ui.separator();
            ui.label("账号节点连接方式");
            ui.text_edit_singleline(&mut app.account.server_url);
            ui.small("请首次填写管理版复制的完整 p2p://管理员节点ID。为防止假节点窃取密码，未固定管理员身份前不会发送账号密码；保存后以后自动连接，无需逐次审批。");
            ui.horizontal(|ui| {
                if ui.selectable_label(!app.account.login_mode_register, "登录").clicked() {
                    app.account.login_mode_register = false;
                }
                if ui.selectable_label(app.account.login_mode_register, "注册新账号").clicked() {
                    app.account.login_mode_register = true;
                }
            });
            ui.separator();
            if app.account.login_mode_register {
                ui.small("QQ号和微信号至少填写一项；两项都填写也可以。");
                ui.label("QQ号");
                ui.text_edit_singleline(&mut app.account.qq);
                ui.label("微信号");
                ui.text_edit_singleline(&mut app.account.wechat);
                ui.label("名字");
                ui.text_edit_singleline(&mut app.account.name);
                ui.label("密码（至少8位）");
                ui.add(egui::TextEdit::singleline(&mut app.account.password).password(true));
                ui.label("头像图片地址（可选，https 图片链接）");
                ui.text_edit_singleline(&mut app.account.avatar_url);
            } else {
                ui.label("QQ号或微信号");
                ui.text_edit_singleline(&mut app.account.login_identifier);
                ui.label("密码");
                ui.add(egui::TextEdit::singleline(&mut app.account.password).password(true));
            }
            ui.add_space(8.0);
            let busy = app.account.pending.is_some();
            let label = if app.account.login_mode_register { "注册并登录" } else { "登录" };
            if ui.add_enabled(!busy, egui::Button::new(label).min_size(vec2(ui.available_width(), 42.0))).clicked() {
                if app.account.login_mode_register {
                    app.account.submit_register(config);
                } else {
                    app.account.submit_login(config);
                }
            }
            if !app.account.status.is_empty() {
                ui.add_space(8.0);
                ui.label(&app.account.status);
            }
        }),
        Mode::Checking => centered_window(ctx, "账号验证中", vec2(360.0, 230.0), |ui| {
            ui.vertical_centered(|ui| {
                ui.heading("正在连接家庭账号服务器");
                ui.label("验证通过后才能进入 EffectCraft");
                ui.spinner();
                ui.label(&app.account.server_url);
            });
        }),
        Mode::Unavailable => centered_window(ctx, "无法验证账号", vec2(420.0, 380.0), |ui| {
            ui.label("管理员手机账号节点当前无法连接。为防止离线绕过封禁，软件暂时保持锁定。");
            ui.label("请粘贴管理版“复制管理员节点 ID”得到的完整 p2p://地址；同 Wi-Fi 优先直连，跨网络自动尝试打洞和公共中继。");
            ui.label("管理员节点地址");
            ui.text_edit_singleline(&mut app.account.server_url);
            if ui.add_enabled(app.account.pending.is_none(), egui::Button::new("保存节点地址并重新连接")).clicked() {
                app.account.retry(config);
            }
            if !app.account.status.is_empty() {
                ui.label(&app.account.status);
            }
        }),
        Mode::Success => centered_window(ctx, "账号成功", vec2(380.0, 280.0), |ui| {
            ui.vertical_centered(|ui| {
                ui.heading("你已成功注册 / 登录账号");
                ui.add_space(12.0);
                ui.label("请点击 OK 退出软件，再次打开软件后即可正常使用。");
                ui.add_space(18.0);
                if ui.button("OK").clicked() {
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
            });
        }),
        Mode::Banned => centered_window(ctx, "账号已被封禁", vec2(400.0, 320.0), |ui| {
            ui.vertical_centered(|ui| {
                ui.heading("账号已被封禁");
                ui.add_space(10.0);
                ui.label(format!("封禁截止时间：{}", app.account.banned_until));
                ui.add_space(8.0);
                ui.label("封禁原因：");
                ui.label(&app.account.ban_reason);
                ui.add_space(18.0);
                if ui.button("OK").clicked() {
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
            });
        }),
        Mode::Editor => {}
    }
}
'''

def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ.get("EFFECTCRAFT_DIR", "")).resolve()
    lib = root / "crates/ui-egui/src/lib.rs"
    app = root / "crates/ui-egui/src/app.rs"
    if not lib.is_file() or not app.is_file():
        raise SystemExit(f"EFFECTCRAFT_DIR must point to EffectCraft source; missing {lib} or {app}")

    account_path = root / "crates/ui-egui/src/account.rs"
    account_path.write_text(ACCOUNT_RS, encoding="utf-8")

    source = lib.read_text(encoding="utf-8")
    source = replace_once(source, "mod app;\n", "mod account;\nmod app;\n", "account module declaration")
    source = replace_once(
        source,
        "    pub(crate) updates_rt: updates_ui::Runtime,\n",
        "    pub(crate) updates_rt: updates_ui::Runtime,\n    pub(crate) account: account::AccountState,\n",
        "account state field",
    )
    lib.write_text(source, encoding="utf-8")

    source = app.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "            updates_rt: updates_ui::Runtime::default(),\n",
        "            updates_rt: updates_ui::Runtime::default(),\n            account: super::account::AccountState::default(),\n",
        "account state initialization",
    )
    source = replace_once(
        source,
        "    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {\n        self.draw(ui, frame);\n    }",
        "    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {\n        self.draw(ui, frame);\n        super::account::show(self, ui.ctx());\n    }",
        "account UI overlay call",
    )
    app.write_text(source, encoding="utf-8")
    print("Installed the first-launch home-Wi-Fi account gate, profile window, server verification and ban lock.")


if __name__ == "__main__":
    main()
