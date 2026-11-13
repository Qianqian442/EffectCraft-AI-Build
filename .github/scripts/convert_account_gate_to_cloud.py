#!/usr/bin/env python3
"""Convert the generated EffectCraft account gate to the shared HTTPS Cloudflare API."""
from __future__ import annotations

import os
import re
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"])
    account_path = root / "crates/ui-egui/src/account.rs"
    if not account_path.is_file():
        raise SystemExit("Run add_home_lan_account_gate.py before the cloud account patch.")

    api_url = os.environ.get("AE_ACCOUNT_API_URL", "").strip().rstrip("/")
    if not api_url.startswith("https://") or not api_url.endswith(".workers.dev"):
        raise SystemExit(
            "AE_ACCOUNT_API_URL must be the deployed HTTPS workers.dev base URL. "
            "Deploy cloudflare-worker first; do not publish a LAN/P2P-only APK."
        )

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

    old_imports = (
        "use std::io::{BufRead, BufReader, Read, Write};\n"
        "use std::net::{TcpListener, TcpStream, ToSocketAddrs};\n"
        "use std::sync::atomic::{AtomicBool, Ordering};\n"
        "use std::sync::mpsc::{self, Receiver, TryRecvError};\n"
        "use std::time::Duration;\n\n"
        'const DEFAULT_SERVER: &str = "p2p://auto";\n'
        "const ACCOUNT_EVENT_PROXY: std::net::SocketAddr = std::net::SocketAddr::new(\n"
        "    std::net::IpAddr::V4(std::net::Ipv4Addr::LOCALHOST), 8790,\n"
        ");\n"
        "static ACCOUNT_EVENT_LISTENER_STARTED: AtomicBool = AtomicBool::new(false);\n\n"
    )
    new_imports = (
        "use std::io::Read;\n"
        "use std::sync::mpsc::{self, Receiver, TryRecvError};\n"
        "use std::time::Duration;\n"
        "use tungstenite::client::IntoClientRequest;\n"
        "use tungstenite::http::HeaderValue;\n"
        "use tungstenite::Message;\n\n"
        f'const DEFAULT_SERVER: &str = "{api_url}";\n'
    )
    source = replace_once(source, old_imports, new_imports, "imports and cloud API URL")

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
        "                    // Cloud tokens are bound to the configured HTTPS API.\n"
        "                    // Do not reuse credentials saved for an old LAN/P2P server.\n"
        "                    if saved.server_url == self.server_url && !saved.token.is_empty() {\n"
        "                        self.token = Some(saved.token);\n"
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
                        let _ = tx.send(Err(format!("实时封禁通知地址无效：{error}")));
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
                                        if tx.send(Ok(value)).is_err() { return; }
                                    }
                                }
                                Ok(Message::Close(_)) => break,
                                Ok(_) => {}
                                Err(_) => break,
                            }
                        }
                    }
                    Err(error) => {
                        let _ = tx.send(Err(format!("实时封禁通知连接失败：{error}")));
                    }
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
                if self.status.is_empty() {
                    self.status = error;
                }
            }
            _ => {}
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
    if 'tungstenite = { version = "0.30"' not in workspace:
        anchor = 'serde_json = { version = "1", features = ["float_roundtrip"] }\n'
        if anchor not in workspace:
            raise SystemExit("Could not add HTTPS dependencies: workspace serde_json anchor is missing.")
        workspace = workspace.replace(
            anchor,
            anchor
            + 'ureq = "3.5"\n'
            + 'tungstenite = { version = "0.30", default-features = false, features = ["handshake", "rustls-tls-webpki-roots"] }\n',
            1,
        )
        workspace_manifest.write_text(workspace, encoding="utf-8")

    ui_manifest = root / "crates/ui-egui/Cargo.toml"
    ui = ui_manifest.read_text(encoding="utf-8")
    if 'tungstenite = { workspace = true }' not in ui:
        anchor = 'image = { workspace = true }\n'
        if anchor not in ui:
            raise SystemExit("Could not add HTTPS dependencies: UI image dependency anchor is missing.")
        ui = ui.replace(anchor, anchor + 'ureq = { workspace = true }\n' + 'tungstenite = { workspace = true }\n', 1)
        ui_manifest.write_text(ui, encoding="utf-8")

    print("Cloud HTTPS account gate installed: shared Cloudflare API, live ban/unban WebSocket, no periodic polling.")


if __name__ == "__main__":
    main()
