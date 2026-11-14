#!/usr/bin/env python3
"""Convert the generated account gate to HTTPS + push-only ban/unban events."""
from __future__ import annotations

import os
import re
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"])
    account_path = root / "crates/ui-egui/src/account.rs"
    if not account_path.is_file():
        raise SystemExit("Run add_home_lan_account_gate.py before this account patch.")
    source = account_path.read_text(encoding="utf-8")
    api_url = os.environ.get("AE_ACCOUNT_API_URL", "").strip().rstrip("/")
    if not api_url.startswith("https://") or not api_url.endswith(".workers.dev"):
        raise SystemExit(
            "Set repository variable AE_ACCOUNT_API_URL to the deployed HTTPS workers.dev URL before building."
        )

    source = replace_once(
        source,
        "//! Home-Wi-Fi-only account gate. The account API is intentionally fail-closed:\n"
        "//! when a saved account cannot be checked against the home server, the editor stays locked.",
        "//! EFFECTCRAFT_CLOUDFLARE_ACCOUNT_GATE_V1\n"
        "//! Cloud account gate. The account API is intentionally fail-closed:\n"
        "//! when a saved account cannot be checked against the cloud server, the editor stays locked.",
        "module documentation",
    )
    source = replace_once(
        source,
        "use std::io::{Read, Write};\n"
        "use std::net::{TcpStream, ToSocketAddrs};\n",
        "use tungstenite::client::IntoClientRequest;\n"
        "use tungstenite::http::HeaderValue;\n"
        "use tungstenite::Message;\n",
        "replace LAN-only transport imports with Cloudflare WebSocket imports",
    )
    source = replace_once(
        source,
        'const DEFAULT_SERVER: &str = "p2p://auto";',
        f'const DEFAULT_SERVER: &str = "{api_url}";',
        "Cloudflare account API URL",
    )
    source = replace_once(
        source,
        "    pending: Option<Receiver<Result<HttpResult, String>>>,\n"
        "    pending_action: Option<Action>,",
        "    pending: Option<Receiver<Result<HttpResult, String>>>,\n"
        "    pending_action: Option<Action>,\n"
        "    pending_started: Option<std::time::Instant>,\n"
        "    events: Option<Receiver<Result<Value, String>>>,\n"
        "    event_started: bool,\n"
        "    node_event_started: bool,\n"
        "    notification_pending: Option<String>,\n"
        "    last_event_signature: Option<String>,\n"
        "    last_server_state: Option<bool>,",
        "account event state fields",
    )
    source = replace_once(
        source,
        "            pending: None,\n"
        "            pending_action: None,",
        "            pending: None,\n"
        "            pending_action: None,\n"
        "            pending_started: None,\n"
        "            events: None,\n"
        "            event_started: false,\n"
        "            node_event_started: false,\n"
        "            notification_pending: None,\n"
        "            last_event_signature: None,\n"
        "            last_server_state: None,",
        "account event state initialization",
    )
    source = replace_once(
        source,
        '                    self.server_url = if saved.server_url.starts_with("p2p://") {\n'
        "                        saved.server_url\n"
        "                    } else {\n"
        "                        DEFAULT_SERVER.to_string()\n"
        "                    };\n"
        "                    if !saved.token.is_empty() {\n"
        "                        self.token = Some(saved.token);\n"
        "                    }",
        '                    if saved.server_url == self.server_url {\n'
        "                        if !saved.token.is_empty() {\n"
        "                            self.token = Some(saved.token);\n"
        "                        }\n"
        "                    }",
        "discard old LAN token and restore cloud token only",
    )
    source = source.replace(
        'self.status = "正在连接家中的账号服务器…".to_string();',
        'self.status = "正在连接云端账号服务器…".to_string();',
    )
    source = source.replace(
        'self.status = "正在连接管理员账号节点…".to_string();',
        'self.status = "正在连接云端账号服务器…".to_string();',
    )
    source = source.replace(
        'ui.label("通过 P2P 自动连接管理员手机账号节点");',
        'ui.label("通过 Cloudflare HTTPS 云端服务连接账号");',
    )
    source = source.replace(
        'ui.label("账号节点连接方式");',
        'ui.label("云端账号服务地址");',
    )
    source = source.replace(
        'ui.small("请首次填写管理版复制的完整 p2p://管理员节点ID。为防止假节点窃取密码，未固定管理员身份前不会发送账号密码；保存后以后自动连接，无需逐次审批。");',
        'ui.small("此地址由构建配置自动设置，账号通信优先直连 Cloudflare，连接失败时自动检测公开代理隧道。");',
    )
    source = source.replace(
        'ui.label("管理员手机账号节点当前无法连接。为防止离线绕过封禁，软件暂时保持锁定。");',
        'ui.label("Cloudflare 账号服务当前无法连接。为防止离线绕过封禁，软件暂时保持锁定。");',
    )
    source = source.replace(
        'ui.label("请粘贴管理版“复制管理员节点 ID”得到的完整 p2p://地址；同 Wi-Fi 优先直连，跨网络自动尝试打洞和公共中继。");',
        'ui.label("系统已尝试直连和可用的公开代理隧道，请检查网络后重试。");',
    )
    source = source.replace(
        'ui.label("管理员节点地址");',
        'ui.label("Cloudflare HTTPS 服务地址");',
    )
    source = source.replace(
        'ui.text_edit_singleline(&mut app.account.server_url);',
        'ui.add_enabled(false, egui::TextEdit::singleline(&mut app.account.server_url));',
    )

    # The server endpoint stays in the signed build configuration only. Do not
    # show the workers.dev hostname, a disabled URL field, or instructions that
    # reveal the configured host in the main APK account screen.
    source = source.replace('ui.label("云端账号服务地址");', "")
    source = source.replace('ui.label("Cloudflare HTTPS 服务地址");', "")
    source = source.replace(
        'ui.small("此地址由构建配置自动设置，账号通信优先直连 Cloudflare，连接失败时自动检测公开代理隧道。");',
        "",
    )
    source = source.replace(
        'ui.add_enabled(false, egui::TextEdit::singleline(&mut app.account.server_url));',
        "",
    )
    source = source.replace(
        'ui.button("保存节点地址并重新连接")',
        'ui.button("重新检测连接")',
    )
    source = source.replace(
        '                        self.last_verified = Some(std::time::Instant::now());\n',
        "",
    )

    live_event_methods = r'''
    // One hibernating account-status WebSocket. It has no timed ping, no
    // reconnect loop and no 10-second Worker polling. A connection is opened
    // once per app session; the Durable Object replays the latest event on
    // the next app launch if this process was stopped.
    fn start_events(&mut self) {
        if self.event_started {
            return;
        }
        let Some(token) = self.token.clone() else { return; };
        let base = self.server_url.trim_end_matches('/')
            .replacen("https://", "wss://", 1);
        let ws_url = format!("{base}/v1/events");
        let (tx, rx) = mpsc::channel();
        self.events = Some(rx);
        self.event_started = true;
        std::thread::spawn(move || {
            let mut request = match ws_url.into_client_request() {
                Ok(request) => request,
                Err(error) => {
                    let _ = tx.send(Err(format!("实时通知地址无效：{error}")));
                    return;
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
                    loop {
                        match socket.read() {
                            Ok(Message::Text(message)) => {
                                if let Ok(value) = serde_json::from_str::<Value>(message.as_str()) {
                                    let _ = tx.send(Ok(value));
                                }
                            }
                            Ok(Message::Ping(payload)) => {
                                if socket.send(Message::Pong(payload)).is_err() {
                                    break;
                                }
                            }
                            Ok(Message::Close(_)) => break,
                            Ok(_) => {}
                            Err(error) => {
                                let _ = tx.send(Err(format!("实时通知连接已断开：{error}")));
                                break;
                            }
                        }
                    }
                }
                Err(error) => {
                    let _ = tx.send(Err(format!("实时通知连接失败：{error}")));
                }
            }
        });
    }

    // Node-presence heartbeat is not used by account ban/unban notifications.
    fn start_node_events(&mut self) {}

    fn poll_events(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let received = match self.events.as_ref().map(|rx| rx.try_recv()) {
            Some(Ok(result)) => Some(result),
            Some(Err(TryRecvError::Disconnected)) => Some(Err("实时通知连接已结束；下次打开软件时会重新同步".to_string())),
            Some(Err(TryRecvError::Empty)) | None => None,
        };
        match received {
            Some(Ok(event)) => {
                let event_type = event.get("type").and_then(Value::as_str).unwrap_or("");
                if event_type == "server_state_changed" {
                    let enabled = event.get("enabled").and_then(Value::as_bool).unwrap_or(false);
                    if self.last_server_state != Some(enabled) {
                        self.last_server_state = Some(enabled);
                        if !enabled {
                            // Stop the editor immediately. Keep the same event
                            // socket open so the later enable event can restore access.
                            self.pending = None;
                            self.pending_action = None;
                            self.mode = Mode::ServerClosed;
                            self.status = "当前服务器已关闭，请等待开发者开启服务器".to_string();
                        } else if self.mode == Mode::ServerClosed || self.mode == Mode::Unavailable {
                            if self.token.is_some() {
                                self.mode = Mode::Checking;
                                self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
                            } else {
                                self.mode = Mode::Auth;
                                self.status.clear();
                            }
                        }
                    }
                } else if event_type == "account_status_changed" {
                    let status = event.get("status").and_then(Value::as_str).unwrap_or("");
                    let banned_until = event.get("banned_until").and_then(Value::as_str).unwrap_or("");
                    let signature = format!("{status}:{banned_until}");
                    // A different expiry is a new ban event even if the account
                    // was already banned. Replayed copies of the same event are ignored.
                    if (status == "banned" || status == "unbanned")
                        && self.last_event_signature.as_deref() != Some(signature.as_str())
                    {
                        self.last_event_signature = Some(signature);
                        self.notification_pending = Some(status.to_string());
                    }
                }
            }
            Some(Err(error)) => {
                self.status = error;
                if self.mode == Mode::Editor {
                    self.mode = Mode::Unavailable;
                }
            }
            None => {}
        }
        if self.pending.is_none() && self.token.is_some() {
            if let Some(_status) = self.notification_pending.take() {
                // The notification is only a wake-up signal. Query the canonical
                // account state once over the short-lived task VPN, then stop it.
                self.mode = Mode::Checking;
                self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
            }
        }
    }
'''
    source = replace_once(
        source,
        "    fn submit_login(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {",
        live_event_methods + "\n    fn submit_login(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {",
        "insert push notification client",
    )

    http_pattern = re.compile(
        r"fn http_request\(url: &str, method: &str, path: &str, body: Value, token: Option<&str>\) -> Result<HttpResult, String> \{.*?\n\}\n\n(?=fn blocking_overlay)",
        re.S,
    )
    http_replacement = r'''fn http_request(url: &str, method: &str, path: &str, body: Value, token: Option<&str>) -> Result<HttpResult, String> {
    if !url.starts_with("https://") {
        return Err("账号服务必须使用 HTTPS 云端地址".to_string());
    }
    let endpoint = format!("{}{}", url.trim_end_matches('/'), path);
    let agent: ureq::Agent = ureq::Agent::config_builder()
        .http_status_as_error(false)
        .timeout_global(Some(Duration::from_secs(15)))
        .build()
        .into();
    let mut request = if method == "GET" {
        agent.get(&endpoint)
    } else {
        agent.post(&endpoint)
    };
    request = request.header("Accept", "application/json");
    if let Some(token) = token {
        request = request.header("Authorization", &format!("Bearer {token}"));
    }
    let mut response = if body.is_null() {
        request.call()
    } else {
        let bytes = serde_json::to_vec(&body).map_err(|error| error.to_string())?;
        request.header("Content-Type", "application/json").send(bytes.as_slice())
    }.map_err(|error| format!("云端请求失败：{error}"))?;
    let status = response.status().as_u16();
    let body_text = response.body_mut().read_to_string().map_err(|error| error.to_string())?;
    let value = serde_json::from_str::<Value>(&body_text)
        .unwrap_or_else(|_| json!({"detail": "服务器返回了无法识别的数据"}));
    Ok(HttpResult { status, body: value })
}

'''
    source, substitutions = http_pattern.subn(http_replacement, source, count=1)
    if substitutions != 1:
        raise SystemExit(f"HTTPS transport replacement expected once, found {substitutions}")

    live_event_call = (
        "    if matches!(app.account.mode, Mode::Editor | Mode::Banned | Mode::ServerClosed | Mode::Unavailable) {\n"
        "        app.account.start_events();\n"
        "        if app.account.mode == Mode::Editor {\n"
        "            app.account.start_node_events();\n"
        "        }\n"
        "        app.account.poll_events(config);\n"
        "    }"
    )
    periodic_block = (
        "    if app.account.mode == Mode::Editor\n"
        "        && app.account.pending.is_none()\n"
        "        && app.account.last_verified.map_or(true, |last| last.elapsed() > std::time::Duration::from_secs(10))\n"
        "    {\n"
        '        app.account.send(Action::Verify, "GET", "/v1/me", Value::Null, config);\n'
        "    }"
    )
    if periodic_block in source:
        source = source.replace(periodic_block, live_event_call, 1)
    elif live_event_call not in source:
        source = replace_once(
            source,
            "    app.account.poll(config);",
            "    app.account.poll(config);\n" + live_event_call,
            "start push events without periodic account polling",
        )
    source = replace_once(
        source,
        "    fn retry(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {\n"
        "        self.status.clear();",
        "    fn retry(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {\n"
        "        self.pending_started = None;\n"
        "        self.event_started = false;\n"
        "        self.events = None;\n"
        "        self.status.clear();",
        "restart server notification socket when the user retries",
    )

    source = source.replace(
        'ui.label("仅连接家中的 Wi-Fi 账号服务器");',
        'ui.label("连接云端账号服务器，支持不同地区和网络");',
    )
    source = source.replace('ui.label("家庭服务器地址");', 'ui.label("云端 HTTPS 服务器地址");')
    source = source.replace(
        'ui.small("把示例地址替换为家中电脑的局域网 IPv4 地址，例如 http://192.168.1.23:8787");',
        'ui.small("请使用 Ae 管理员提供的 Cloudflare workers.dev HTTPS 地址");',
    )
    source = source.replace(
        'ui.heading("正在连接家庭账号服务器");',
        'ui.heading("正在连接云端账号服务器");',
    )
    source = source.replace(
        'ui.label("家中的账号服务器当前无法连接。为防止离线绕过封禁，软件暂时保持锁定。");',
        'ui.label("云端账号服务器当前无法连接。为防止离线绕过封禁，软件暂时保持锁定。");',
    )
    source = source.replace(
        'ui.label("请确认手机和服务器电脑连接同一个家庭 Wi-Fi，且服务器电脑保持开机。");',
        'ui.label("请检查网络连接后重试。账号验证成功后即可进入软件。");',
    )

    # Keep every account operation bounded and allow the user to leave any
    # verification screen. The worker thread is detached; dropping its receiver
    # prevents a late response from changing the UI, while ureq enforces a
    # separate 15-second network timeout.
    send_anchor = (
        "        self.pending = Some(rx);\\n"
        "        self.pending_action = Some(action);\\n"
        "        self.status = \\"正在连接管理员账号节点…\\".to_string();"
    )
    send_replacement = (
        "        self.pending = Some(rx);\\n"
        "        self.pending_action = Some(action);\\n"
        "        self.pending_started = Some(std::time::Instant::now());\\n"
        "        self.status = \\"正在连接云端账号服务器…\\".to_string();"
    )
    if source.count(send_anchor) != 1:
        raise SystemExit("Could not locate account request start for timeout tracking")
    source = source.replace(send_anchor, send_replacement, 1)

    poll_anchor = (
        "    fn poll(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {\\n"
        "        let received = match self.pending.as_ref().map(|rx| rx.try_recv()) {"
    )
    poll_replacement = (
        "    fn poll(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {\\n"
        "        if self.pending_started.map_or(false, |started| started.elapsed() >= std::time::Duration::from_secs(20)) {\\n"
        "            self.pending = None;\\n"
        "            self.pending_started = None;\\n"
        "            let expired_action = self.pending_action.take().unwrap_or(Action::Verify);\\n"
        "            match expired_action {\\n"
        "                Action::Verify => self.mode = Mode::Unavailable,\\n"
        "                Action::Login | Action::Register => self.mode = Mode::Auth,\\n"
        "                _ => {},\\n"
        "            }\\n"
        "            self.status = \\"请求超时，已结束本次等待。请检查网络后重试。\\".to_string();\\n"
        "            return;\\n"
        "        }\\n"
        "        let received = match self.pending.as_ref().map(|rx| rx.try_recv()) {"
    )
    if source.count(poll_anchor) != 1:
        raise SystemExit("Could not locate account result polling for bounded timeout")
    source = source.replace(poll_anchor, poll_replacement, 1)

    pending_clear_anchor = (
        "        self.pending = None;\\n"
        "        let action = self.pending_action.take().unwrap_or(Action::Verify);"
    )
    pending_clear_replacement = (
        "        self.pending = None;\\n"
        "        self.pending_started = None;\\n"
        "        let action = self.pending_action.take().unwrap_or(Action::Verify);"
    )
    if source.count(pending_clear_anchor) != 1:
        raise SystemExit("Could not locate account pending cleanup after response")
    source = source.replace(pending_clear_anchor, pending_clear_replacement, 1)

    cancel_method = r\'''    fn cancel_pending_and_return(&mut self) {
        self.pending = None;
        self.pending_action = None;
        self.pending_started = None;
        self.mode = Mode::Auth;
        self.status = "本次操作已取消，已返回登录页面。可以检查网络后重新尝试。".to_string();
    }

\'''
    method_anchor = "    fn retry(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {"
    if source.count(method_anchor) != 1:
        raise SystemExit("Could not locate account retry method for cancel action")
    source = source.replace(method_anchor, cancel_method + method_anchor, 1)

    auth_busy_anchor = (
        "            if ui.add_enabled(!busy, egui::Button::new(label).min_size(vec2(ui.available_width(), 42.0))).clicked() {\\n"
        "                if app.account.login_mode_register {\\n"
        "                    app.account.submit_register(config);\\n"
        "                } else {\\n"
        "                    app.account.submit_login(config);\\n"
        "                }\\n"
        "            }"
    )
    auth_busy_replacement = auth_busy_anchor + (
        "\\n            if busy && ui.button(\\"取消并返回登录\\").clicked() {\\n"
        "                app.account.cancel_pending_and_return();\\n"
        "            }"
    )
    if source.count(auth_busy_anchor) != 1:
        raise SystemExit("Could not add cancel button to login/register screen")
    source = source.replace(auth_busy_anchor, auth_busy_replacement, 1)

    checking_anchor = (
        "        Mode::Checking => centered_window(ctx, \\"账号验证中\\", vec2(360.0, 230.0), |ui| {\\n"
        "            ui.vertical_centered(|ui| {\\n"
        "                ui.heading(\\"正在连接云端账号服务器\\");\\n"
        "                ui.label(\\"验证通过后才能进入 EffectCraft\\");\\n"
        "                ui.spinner();\\n"
        "                ui.label(&app.account.server_url);\\n"
        "            });\\n"
        "        }),"
    )
    checking_replacement = (
        "        Mode::Checking => centered_window(ctx, \\"账号验证中\\", vec2(360.0, 250.0), |ui| {\\n"
        "            ui.vertical_centered(|ui| {\\n"
        "                ui.heading(\\"正在验证账号…\\");\\n"
        "                ui.label(\\"验证通过后才能进入 EffectCraft\\");\\n"
        "                ui.spinner();\\n"
        "                ui.label(\\"网络无响应时可取消返回；本次等待最长 20 秒。\\");\\n"
        "                if ui.button(\\"取消并返回登录\\").clicked() {\\n"
        "                    app.account.cancel_pending_and_return();\\n"
        "                }\\n"
        "            });\\n"
        "        }),"
    )
    if source.count(checking_anchor) != 1:
        raise SystemExit("Could not replace checking screen with cancellable version")
    source = source.replace(checking_anchor, checking_replacement, 1)

    unavailable_anchor = (
        "            if !app.account.status.is_empty() {\\n"
        "                ui.label(&app.account.status);\\n"
        "            }\\n"
        "        }),\\n"
        "        Mode::Success"
    )
    unavailable_replacement = (
        "            if ui.button(\\"返回登录页面\\").clicked() {\\n"
        "                app.account.cancel_pending_and_return();\\n"
        "            }\\n"
        "            if !app.account.status.is_empty() {\\n"
        "                ui.label(&app.account.status);\\n"
        "            }\\n"
        "        }),\\n"
        "        Mode::Success"
    )
    if source.count(unavailable_anchor) != 1:
        raise SystemExit("Could not add a return action to the unavailable page")
    source = source.replace(unavailable_anchor, unavailable_replacement, 1)
    if "last_verified" in source or "TcpStream" in source or "192.168.1.100" in source:
        raise SystemExit("LAN/10-second account code remains after cloud conversion.")
    account_path.write_text(source, encoding="utf-8")

    workspace_manifest = root / "Cargo.toml"
    workspace = workspace_manifest.read_text(encoding="utf-8")
    if 'ureq = { version = "3.5", features = ["socks-proxy"] }' not in workspace:
        if 'ureq = "3.5"' in workspace:
            workspace = workspace.replace(
                'ureq = "3.5"',
                'ureq = { version = "3.5", features = ["socks-proxy"] }',
                1,
            )
        else:
            workspace = replace_once(
                workspace,
                'serde_json = { version = "1", features = ["float_roundtrip"] }\n',
                'serde_json = { version = "1", features = ["float_roundtrip"] }\n'
                'ureq = { version = "3.5", features = ["socks-proxy"] }\n',
                "workspace ureq SOCKS5 dependency",
            )
    if 'tungstenite = { version = "0.30"' not in workspace:
        workspace = replace_once(
            workspace,
            'serde_json = { version = "1", features = ["float_roundtrip"] }\n',
            'serde_json = { version = "1", features = ["float_roundtrip"] }\n'
            'tungstenite = { version = "0.30", default-features = false, features = ["handshake", "rustls-tls-webpki-roots"] }\n',
            "workspace WebSocket dependency",
        )
    workspace_manifest.write_text(workspace, encoding="utf-8")

    ui_manifest = root / "crates/ui-egui/Cargo.toml"
    ui = ui_manifest.read_text(encoding="utf-8")
    if 'tungstenite = { workspace = true }' not in ui:
        ui = replace_once(
            ui,
            'image = { workspace = true }\n',
            'image = { workspace = true }\n'
            'ureq = { workspace = true }\n'
            'tungstenite = { workspace = true }\n',
            "UI HTTPS/WebSocket dependencies",
        )
        ui_manifest.write_text(ui, encoding="utf-8")

    print("Cloud account gate installed: one startup verification; live ban/unban events; no periodic polling.")


if __name__ == "__main__":
    main()
