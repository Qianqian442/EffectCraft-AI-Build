#!/usr/bin/env python3
"""Install a first-launch home-LAN account gate into the shared EffectCraft egui app."""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "EFFECTCRAFT_HOME_LAN_ACCOUNT_GATE_V1"

ACCOUNT_RS = r'''// EFFECTCRAFT_HOME_LAN_ACCOUNT_GATE_V1
//! Admin-phone LAN account gate. The account API is intentionally fail-closed:
//! when a saved account cannot be checked against the admin phone, the editor stays locked.
use crate::EffectcraftApp;
use egui::{Align2, Color32, Id, Order, Sense, Stroke, StrokeKind, Vec2, pos2, vec2};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs, UdpSocket};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::time::Duration;

const DEFAULT_SERVER: &str = "";

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
    #[serde(default)]
    user: Option<User>,
    #[serde(default)]
    node_opt_in: bool,
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
    node_opt_in: bool,
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
            node_opt_in: false,
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
    pub(crate) fn allows_startup_notice(&self) -> bool {
        self.mode == Mode::Editor
    }

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
                    if saved.server_url.starts_with("http://") {
                        self.server_url = saved.server_url;
                    }
                    self.node_opt_in = saved.node_opt_in;
                    self.user = saved.user;
                    if !saved.token.is_empty() {
                        self.token = Some(saved.token);
                    }
                }
            }
        }
        if self.token.is_some() {
            // Open the editor from the locally cached session first; verify bans in the background.
            self.mode = if self.user.is_some() { Mode::Editor } else { Mode::Checking };
            self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
        } else {
            self.mode = Mode::Auth;
        }
    }

    fn persist(&self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let Some(store) = config else { return; };
        let saved = SavedAccount {
            server_url: self.server_url.clone(),
            token: self.token.clone().unwrap_or_default(),
            user: self.user.clone(),
            node_opt_in: self.node_opt_in,
        };
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
        self.status = "正在连接家中的账号服务器…".to_string();
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

    fn choose_avatar(&mut self) {
        let selected = rfd::FileDialog::new()
            .add_filter("图片", &["png", "jpg", "jpeg", "webp"])
            .pick_file();
        let Some(path) = selected else { return; };
        match std::fs::read(&path) {
            Ok(bytes) if !bytes.is_empty() && bytes.len() <= 2 * 1024 * 1024 => {
                let mime = match path.extension().and_then(|v| v.to_str()).unwrap_or("").to_ascii_lowercase().as_str() {
                    "jpg" | "jpeg" => "image/jpeg",
                    "webp" => "image/webp",
                    _ => "image/png",
                };
                self.avatar_url = format!("data:{};base64,{}", mime, base64_encode(&bytes));
                self.status = "头像已选择，将随注册资料上传".to_string();
            }
            Ok(_) => self.status = "头像文件为空或超过2MB，请选择较小的图片".to_string(),
            Err(error) => self.status = format!("读取头像失败：{}", error),
        }
    }

    fn submit_register(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let qq = self.qq.trim();
        let wechat = self.wechat.trim();
        if qq.is_empty() && wechat.is_empty() {
            self.status = "QQ号和微信号至少填写一项".to_string();
            return;
        }
        if !qq.is_empty() && !qq.chars().all(|c| c.is_ascii_digit()) {
            self.status = "QQ号只能填写数字".to_string();
            return;
        }
        if self.name.trim().is_empty() {
            self.status = "请填写名字".to_string();
            return;
        }
        if self.password.chars().count() < 8 {
            self.status = "密码至少8位".to_string();
            return;
        }
        // Save the registration profile locally before any network request.
        self.user = Some(User {
            id: String::new(),
            qq: qq.to_string(),
            wechat: wechat.to_string(),
            name: self.name.trim().to_string(),
            avatar_url: self.avatar_url.trim().to_string(),
            created_at: String::new(),
            banned_until: None,
            ban_reason: String::new(),
        });
        self.persist(config);
        self.status = "注册资料已先保存在本机，正在尝试同步账号服务器…".to_string();
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
                self.status = format!("无法连接管理员手机账号服务器：{error}");
                if matches!(action, Action::Verify) && self.user.is_none() {
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
                if matches!(action, Action::Verify) && self.user.is_none() {
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
                        self.mode = Mode::Editor;
                        self.password.clear();
                        self.last_verified = Some(std::time::Instant::now());
                        self.status = "账号已登录，已进入剪辑界面；账号资料已保存在本机，后台继续验证管理员状态。".to_string();
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
            self.mode = Mode::Checking;
            self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
        } else {
            self.mode = Mode::Auth;
        }
    }
}

fn base64_encode(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity((bytes.len() + 2) / 3 * 4);
    for chunk in bytes.chunks(3) {
        let a = chunk[0] as u32;
        let b = if chunk.len() > 1 { chunk[1] as u32 } else { 0 };
        let c = if chunk.len() > 2 { chunk[2] as u32 } else { 0 };
        let n = (a << 16) | (b << 8) | c;
        out.push(TABLE[((n >> 18) & 63) as usize] as char);
        out.push(TABLE[((n >> 12) & 63) as usize] as char);
        out.push(if chunk.len() > 1 { TABLE[((n >> 6) & 63) as usize] as char } else { '=' });
        out.push(if chunk.len() > 2 { TABLE[(n & 63) as usize] as char } else { '=' });
    }
    out
}

fn discover_admin_server() -> Result<String, String> {
    let socket = UdpSocket::bind("0.0.0.0:0").map_err(|e| e.to_string())?;
    socket.set_broadcast(true).map_err(|e| e.to_string())?;
    socket.set_read_timeout(Some(Duration::from_millis(1800))).map_err(|e| e.to_string())?;
    socket.send_to(b"EFFECTCRAFT_ACCOUNT_DISCOVER_V1", "255.255.255.255:8789")
        .map_err(|e| e.to_string())?;
    let mut buffer = [0u8; 512];
    let (length, _) = socket.recv_from(&mut buffer).map_err(|e| e.to_string())?;
    let response = std::str::from_utf8(&buffer[..length]).map_err(|e| e.to_string())?;
    let url = response.strip_prefix("EFFECTCRAFT_ACCOUNT_SERVER_V1|")
        .ok_or_else(|| "管理员手机返回了无法识别的发现响应".to_string())?;
    if !url.starts_with("http://") || !url.ends_with(":8788") {
        return Err("管理员手机账号服务器地址无效".to_string());
    }
    Ok(url.to_string())
}

fn http_request(url: &str, method: &str, path: &str, body: Value, token: Option<&str>) -> Result<HttpResult, String> {
    // Refresh the admin-phone address on each request; its Wi-Fi IP may change.
    let discovered = discover_admin_server().ok();
    let target_url = discovered.as_deref().unwrap_or(url);
    let rest = target_url.strip_prefix("http://").ok_or_else(|| "未发现管理员手机账号服务器，请确认管理员手机已开启服务且两台手机连接同一 Wi-Fi".to_string())?;
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
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(7)).map_err(|e| format!("连接管理员手机失败：{e}"))?;
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

fn blocking_overlay(ctx: &egui::Context) {
    let screen = ctx.content_rect();
    // Keep the dimming layer above the editor but below the foreground auth dialogs.
    egui::Area::new(Id::new("effectcraft-account-blocking-overlay"))
        .order(Order::Middle)
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
                    let mut node_opt_in = app.account.node_opt_in;
                    if ui.checkbox(&mut node_opt_in, "允许本机参与 EffectCraft 节点互联（可随时关闭）").changed() {
                        app.account.node_opt_in = node_opt_in;
                        app.account.persist(config);
                    }
                    ui.small("开启后本机将通过加密连接参与节点在线互联；不会自动共享账号密码或媒体文件。关闭后停止本机节点连接。");
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
                ui.label("连接管理员手机开启的 EffectCraft 账号服务器");
            });
            ui.separator();
            ui.label("管理员手机账号服务器地址");
            ui.text_edit_singleline(&mut app.account.server_url);
            ui.small("与管理版安装在同一台手机：填写 http://127.0.0.1:8788。若管理版和主 APK 在两台手机：填写管理版显示的 Wi-Fi 地址（端口 8788），两台手机连接同一 Wi-Fi。");
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
                ui.label("QQ号（可选）");
                ui.text_edit_singleline(&mut app.account.qq);
                ui.label("微信号（可选）");
                ui.text_edit_singleline(&mut app.account.wechat);
                ui.small("QQ号和微信号填写其中一个即可，至少填写一项。");
                ui.label("名字");
                ui.text_edit_singleline(&mut app.account.name);
                ui.label("密码（至少8位）");
                ui.add(egui::TextEdit::singleline(&mut app.account.password).password(true));
                ui.label("头像（可选）");
                ui.horizontal(|ui| {
                    if ui.button("从手机相册选择").clicked() {
                        app.account.choose_avatar();
                    }
                    if !app.account.avatar_url.is_empty() {
                        ui.label("已选择头像");
                        if ui.button("清除").clicked() {
                            app.account.avatar_url.clear();
                        }
                    } else {
                        ui.label("尚未选择");
                    }
                });
                ui.small("支持 PNG、JPG、WebP，单张最大2MB；取消选择不会影响注册。");
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
        Mode::Unavailable => centered_window(ctx, "无法验证账号", vec2(400.0, 300.0), |ui| {
            ui.label("管理员手机账号服务器当前无法连接。为防止离线绕过封禁，软件暂时保持锁定。");
            ui.label("请确认两台手机连接同一个 Wi-Fi，并确认管理版已开启账号服务器。");
            ui.label(format!("服务器地址：{}", app.account.server_url));
            if ui.add_enabled(app.account.pending.is_none(), egui::Button::new("重新连接")).clicked() {
                app.account.retry(config);
            }
            if !app.account.status.is_empty() {
                ui.label(&app.account.status);
            }
        }),
        Mode::Success => {},

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
    print("Installed the admin-phone LAN account gate, profile window, server verification and ban lock.")


if __name__ == "__main__":
    main()
