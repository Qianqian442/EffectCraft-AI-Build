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
    api_url = os.environ.get("AE_ACCOUNT_API_URL", "").strip().rstrip("/")
    if not api_url.startswith("https://") or not api_url.endswith(".workers.dev"):
        raise SystemExit(
            "Set repository variable AE_ACCOUNT_API_URL to the deployed HTTPS workers.dev URL before building."
        )

    account_path = root / "crates/ui-egui/src/account.rs"
    if not account_path.is_file():
        raise SystemExit("Run add_home_lan_account_gate.py before this cloud-account patch.")
    source = account_path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        "//! Admin-phone LAN account gate. The account API is intentionally fail-closed:\n"
        "//! when a saved account cannot be checked against the admin phone, the editor stays locked.",
        "//! Cloud account gate. The account API is intentionally fail-closed:\n"
        "//! when a saved account cannot be checked against the cloud server, the editor stays locked.",
        "module documentation",
    )
    source = replace_once(
        source,
        "use std::io::{Read, Write};\n"
        "use std::net::{TcpStream, ToSocketAddrs};\n"
        "use std::sync::mpsc::{self, Receiver, TryRecvError};\n"
        "use std::time::Duration;\n\n"
        'const DEFAULT_SERVER: &str = "http://192.168.1.100:8788";',
        "use std::sync::mpsc::{self, Receiver, TryRecvError};\n"
        "use std::sync::{Arc, atomic::{AtomicBool, Ordering}};\n"
        "use std::time::Duration;\n"
        "use tungstenite::client::IntoClientRequest;\n"
        "use tungstenite::http::HeaderValue;\n"
        "use tungstenite::Message;\n\n"
        f'const DEFAULT_SERVER: &str = "{api_url}";',
        "cloud client imports and API URL",
    )
    source = replace_once(
        source,
        "    pending: Option<Receiver<Result<HttpResult, String>>>,\n"
        "    pending_action: Option<Action>,\n"
        "    last_verified: Option<std::time::Instant>,",
        "    pending: Option<Receiver<Result<HttpResult, String>>>,\n"
        "    pending_action: Option<Action>,\n"
        "    events: Option<Receiver<Result<Value, String>>>,\n"
        "    event_started: bool,\n"
        "    node_event_started: bool,\n"
        "    node_event_control: Option<Arc<AtomicBool>>,\n"
        "    notification_pending: Option<String>,",
        "account event state fields",
    )
    source = replace_once(
        source,
        "            pending: None,\n"
        "            pending_action: None,\n"
        "            last_verified: None,",
        "            pending: None,\n"
        "            pending_action: None,\n"
        "            events: None,\n"
        "            event_started: false,\n"
        "            node_event_started: false,\n"
        "            node_event_control: None,\n"
        "            notification_pending: None,",
        "account event state initialization",
    )
    # The LAN gate persists an HTTP URL and node_opt_in. Never restore a
    # legacy LAN endpoint or its bearer token after switching to the cloud API.
    legacy_saved = (
        '                    if saved.server_url.starts_with("http://") {\\n'
        "                        self.server_url = saved.server_url;\\n"
        "                    }\\n"
        "                    self.node_opt_in = saved.node_opt_in;\\n"
        "                    if !saved.token.is_empty() {\\n"
        "                        self.token = Some(saved.token);\\n"
        "                    }"
    )
    cloud_saved = (
        "                    if saved.server_url == self.server_url {\\n"
        "                        if !saved.token.is_empty() {\\n"
        "                            self.token = Some(saved.token);\\n"
        "                        }\\n"
        "                    }"
    )
    if legacy_saved in source:
        source = source.replace(legacy_saved, cloud_saved, 1)
    elif cloud_saved not in source:
        raise SystemExit("saved account migration: neither legacy nor cloud-safe block found")

    source = source.replace(
        'self.status = "正在连接家中的账号服务器…".to_string();',
        'self.status = "正在连接云端账号服务器…".to_string();',
    )
    source = source.replace(
        '                        self.last_verified = Some(std::time::Instant::now());\n',
        "",
    )

    live_event_methods = r'''
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
            let mut reconnect_delay = 3u64;
            loop {
                let mut request = match ws_url.clone().into_client_request() {
                    Ok(request) => request,
                    Err(error) => {
                        let _ = tx.send(Err(format!("实时通知地址无效：{error}")));
                        std::thread::sleep(Duration::from_secs(reconnect_delay));
                        reconnect_delay = (reconnect_delay * 2).min(600);
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
                        reconnect_delay = 3;
                        loop {
                            match socket.read() {
                                Ok(Message::Text(message)) => {
                                    if let Ok(value) = serde_json::from_str::<Value>(message.as_str()) {
                                        let _ = tx.send(Ok(value));
                                    }
                                }
                                Ok(Message::Close(_)) => break,
                                Ok(_) => {}
                                Err(_) => break,
                            }
                        }
                    }
                    Err(error) => {
                        let _ = tx.send(Err(format!("实时通知连接失败：{error}")));
                    }
                }
                std::thread::sleep(Duration::from_secs(reconnect_delay));
                reconnect_delay = (reconnect_delay * 2).min(600);
            }
        });
    }

    fn start_node_events(&mut self) {
        if self.node_event_started {
            return;
        }
        let Some(token) = self.token.clone() else { return; };
        let base = self.server_url.trim_end_matches('/')
            .replacen("https://", "wss://", 1);
        let ws_url = format!("{base}/v1/nodes/events");
        self.node_event_started = true;
        let active = Arc::new(AtomicBool::new(true));
        self.node_event_control = Some(active.clone());
        std::thread::spawn(move || {
            let mut reconnect_delay = 3u64;
            while active.load(Ordering::Relaxed) {
                let mut request = match ws_url.clone().into_client_request() {
                    Ok(request) => request,
                    Err(_) => {
                        std::thread::sleep(Duration::from_secs(reconnect_delay));
                        reconnect_delay = (reconnect_delay * 2).min(600);
                        continue;
                    }
                };
                let authorization = match HeaderValue::from_str(&format!("Bearer {token}")) {
                    Ok(value) => value,
                    Err(_) => return,
                };
                request.headers_mut().insert("Authorization", authorization);
                match tungstenite::connect(request) {
                    Ok((mut socket, _)) => {
                        reconnect_delay = 3;
                        loop {
                            // The hub treats this authenticated connection as this
                            // account's online phone node. Ping/pong keeps presence
                            // alive without forwarding arbitrary peer payloads.
                            if !active.load(Ordering::Relaxed) {
                                let _ = socket.close(None);
                                break;
                            }
                            if socket.send(Message::Text("ping".into())).is_err() {
                                break;
                            }
                            match socket.read() {
                                Ok(Message::Close(_)) => break,
                                Ok(Message::Text(_)) | Ok(Message::Pong(_)) => {
                                    std::thread::sleep(Duration::from_secs(25));
                                }
                                Ok(_) => {
                                    std::thread::sleep(Duration::from_secs(25));
                                }
                                Err(_) => break,
                            }
                        }
                    }
                    Err(_) => {}
                }
                if !active.load(Ordering::Relaxed) { break; }
                std::thread::sleep(Duration::from_secs(reconnect_delay));
                reconnect_delay = (reconnect_delay * 2).min(600);
            }
        });
    }

    fn poll_events(&mut self, config: Option<&dyn effectcraft_engine::config::ConfigStore>) {
        let received = match self.events.as_ref().map(|rx| rx.try_recv()) {
            Some(Ok(result)) => Some(result),
            Some(Err(TryRecvError::Disconnected)) => Some(Err("实时通知连接已结束".to_string())),
            Some(Err(TryRecvError::Empty)) | None => None,
        };
        if let Some(Ok(event)) = received {
            if event.get("type").and_then(Value::as_str) == Some("account_status_changed") {
                let status = event.get("status").and_then(Value::as_str).unwrap_or("");
                // The Durable Object replays the last status after each connection.
                // Verify only when the local launch/previous state differs.
                let already_matches = (status == "banned" && self.mode == Mode::Banned)
                    || (status == "unbanned" && self.mode == Mode::Editor);
                if !already_matches && (status == "banned" || status == "unbanned") {
                    self.notification_pending = Some(status.to_string());
                }
            }
        }
        if self.pending.is_none() && self.token.is_some() {
            if let Some(status) = self.notification_pending.take() {
                let already_matches = (status == "banned" && self.mode == Mode::Banned)
                    || (status == "unbanned" && self.mode == Mode::Editor);
                if !already_matches {
                    self.mode = Mode::Checking;
                    self.send(Action::Verify, "GET", "/v1/me", Value::Null, config);
                }
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

    source = replace_once(
        source,
        "    app.account.ensure_loaded(config);\n"
        "    app.account.poll(config);\n"
        "    if app.account.mode == Mode::Editor\n"
        "        && app.account.pending.is_none()\n"
        "        && app.account.last_verified.map_or(true, |last| last.elapsed() > std::time::Duration::from_secs(10))\n"
        "    {\n"
        '        app.account.send(Action::Verify, "GET", "/v1/me", Value::Null, config);\n'
        "    }",
        "    app.account.ensure_loaded(config);\n"
        "    app.account.poll(config);\n"
        "    if matches!(app.account.mode, Mode::Editor | Mode::Banned) {\n"
        "        app.account.start_events();\n"
        "        if app.account.mode == Mode::Editor && app.account.node_opt_in {\n"
        "            app.account.start_node_events();\n"
        "        } else if let Some(active) = app.account.node_event_control.as_ref() {\n"
        "            active.store(false, Ordering::Relaxed);\n"
        "            app.account.node_event_started = false;\n"
        "        }\n"
        "        app.account.poll_events(config);\n"
        "    }",
        "remove 10-second polling and listen for events",
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
    source = source.replace(
        'ui.label("管理员手机账号服务器地址");',
        'ui.label("云端账号服务器地址（已预设）");',
    )
    source = source.replace(
        'ui.small("请填写管理版“账号服务器”面板显示的 Wi-Fi 地址，端口为 8788，例如 http://192.168.1.23:8788。两台手机必须连接同一个 Wi-Fi。");',
        'ui.small("已预设 Cloudflare 云端地址，无需管理员手机开机，也无需连接同一个 Wi-Fi。");',
    )
    source = source.replace(
        'ui.label("连接管理员手机开启的 EffectCraft 账号服务器");',
        'ui.label("连接 EffectCraft 云端账号服务");',
    )
    source = source.replace(
        'ui.small("开启后本机将通过加密连接参与节点在线互联；不会自动共享账号密码或媒体文件。关闭后停止本机节点连接。");',
        'ui.small("开启后本机尝试保持跨地区节点在线连接；关闭后停止本机节点连接。节点间加密配对和媒体转发仍需后续版本完成。");',
    )
    if "管理员手机账号服务器地址" in source or "必须连接同一个 Wi-Fi" in source:
        raise SystemExit("LAN-only account UI text remains after cloud conversion.")

    if "last_verified" in source or "TcpStream" in source or "192.168.1.100" in source:
        raise SystemExit("LAN/10-second account code remains after cloud conversion.")
    account_path.write_text(source, encoding="utf-8")

    workspace_manifest = root / "Cargo.toml"
    workspace = workspace_manifest.read_text(encoding="utf-8")
    if 'tungstenite = { version = "0.30"' not in workspace:
        workspace = replace_once(
            workspace,
            'serde_json = { version = "1", features = ["float_roundtrip"] }\n',
            'serde_json = { version = "1", features = ["float_roundtrip"] }\n'
            'ureq = "3.5"\n'
            'tungstenite = { version = "0.30", default-features = false, features = ["handshake", "rustls-tls-webpki-roots"] }\n',
            "workspace HTTPS/WebSocket dependencies",
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
