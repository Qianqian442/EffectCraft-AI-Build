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
        "use std::net::{TcpStream, ToSocketAddrs};\n"
        "use std::sync::mpsc::{self, Receiver, TryRecvError};\n"
        "use std::time::Duration;\n",
        "use std::sync::mpsc::{self, Receiver, TryRecvError};\n"
        "use std::time::Duration;\n",
        "cloud client imports",
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
        "    events: Option<Receiver<Result<Value, String>>>,\n"
        "    event_started: bool,\n"
        "    node_event_started: bool,\n"
        "    notification_pending: Option<String>,",
        "account event state fields",
    )
    source = replace_once(
        source,
        "            pending: None,\n"
        "            pending_action: None,",
        "            pending: None,\n"
        "            pending_action: None,\n"
        "            events: None,\n"
        "            event_started: false,\n"
        "            node_event_started: false,\n"
        "            notification_pending: None,",
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
    source = source.replace(
        'ui.button("保存节点地址并重新连接")',
        'ui.button("重新检测连接")',
    )
    source = source.replace(
        '                        self.last_verified = Some(std::time::Instant::now());\n',
        "",
    )

    live_event_methods = r'''
    // No persistent WebSocket or timed polling. One-shot ban/unban push
    // messages are handled by the native notification bridge.
    fn start_events(&mut self) {}

    fn start_node_events(&mut self) {}

    fn poll_events(&mut self, _config: Option<&dyn effectcraft_engine::config::ConfigStore>) {}
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
        "    if matches!(app.account.mode, Mode::Editor | Mode::Banned) {\n"
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
