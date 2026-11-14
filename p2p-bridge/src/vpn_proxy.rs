//! Loopback SOCKS5 adapter for the on-demand EffectCraft account VPN.
//!
//! Hev tun2socks connects to this loopback listener. The listener accepts only
//! authenticated SOCKS5 clients and only the configured Cloudflare Worker IPs
//! on TCP/443. It then creates a Noise-authenticated libp2p stream to the admin
//! phone; the admin side performs the final allowlist check before egress.

use std::{
    collections::HashSet,
    net::IpAddr,
    sync::{Mutex, OnceLock},
};

use futures::io::{AsyncReadExt as _, AsyncWriteExt as _};
use libp2p::{PeerId, StreamProtocol};
use libp2p_stream::Control;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
};
use tokio_util::compat::FuturesAsyncReadCompatExt;

use crate::vpn_stream::{is_allowed_destination, PROTOCOL_NAME};

const LOCAL_SOCKS_ADDRESS: &str = "127.0.0.1:10808";

#[derive(Clone, Default)]
struct WorkerConfig {
    host: String,
    ips: HashSet<IpAddr>,
    secret: String,
}

static WORKER_CONFIG: OnceLock<Mutex<Option<WorkerConfig>>> = OnceLock::new();
static VPN_CONTROL_TOKEN: OnceLock<Mutex<Option<String>>> = OnceLock::new();
static ADMIN_PEER: OnceLock<Mutex<Option<PeerId>>> = OnceLock::new();

fn vpn_control_token_slot() -> &'static Mutex<Option<String>> {
    VPN_CONTROL_TOKEN.get_or_init(|| Mutex::new(None))
}

pub fn set_vpn_control_token(token: &str) -> Result<(), String> {
    if token.len() != 64 || !token.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("本地 VPN 控制密钥格式无效".to_string());
    }
    let mut slot = vpn_control_token_slot().lock().map_err(|_| "VPN 控制密钥锁不可用".to_string())?;
    *slot = Some(token.to_string());
    Ok(())
}

pub fn get_vpn_control_token() -> Option<String> {
    vpn_control_token_slot().lock().ok().and_then(|slot| slot.clone())
}

fn worker_config() -> &'static Mutex<Option<WorkerConfig>> {
    WORKER_CONFIG.get_or_init(|| Mutex::new(None))
}

fn admin_peer_slot() -> &'static Mutex<Option<PeerId>> {
    ADMIN_PEER.get_or_init(|| Mutex::new(None))
}

pub fn configure_worker(host: &str, ip_csv: &str, secret: &str) -> Result<(), String> {
    if !is_allowed_destination(host, 443) {
        return Err("账号 VPN 只允许配置 workers.dev 主机名".to_string());
    }
    if secret.len() < 24 || secret.len() > 128 || !secret.is_ascii() {
        return Err("本地 SOCKS5 临时密钥长度不正确".to_string());
    }

    let mut ips = HashSet::new();
    for entry in ip_csv.split(',').map(str::trim).filter(|s| !s.is_empty()) {
        let ip: IpAddr = entry.parse().map_err(|_| format!("Worker IP 格式错误：{entry}"))?;
        if !crate::vpn_stream::is_public_ip(ip) {
            return Err("Worker DNS 结果包含非公网地址，已拒绝启动 VPN".to_string());
        }
        ips.insert(ip);
    }
    if ips.is_empty() || ips.len() > 32 {
        return Err("没有可用的 Worker 公网地址，或地址数量超出限制".to_string());
    }

    let mut slot = worker_config().lock().map_err(|_| "VPN 配置锁不可用".to_string())?;
    *slot = Some(WorkerConfig {
        host: host.to_ascii_lowercase(),
        ips,
        secret: secret.to_string(),
    });
    Ok(())
}

pub fn clear_worker_config() {
    if let Ok(mut slot) = worker_config().lock() {
        *slot = None;
    }
}

pub fn set_admin_peer(peer: PeerId) {
    if let Ok(mut slot) = admin_peer_slot().lock() {
        *slot = Some(peer);
    }
}

fn get_admin_peer() -> Option<PeerId> {
    admin_peer_slot().lock().ok().and_then(|slot| slot.as_ref().cloned())
}

fn get_worker_config() -> Option<WorkerConfig> {
    worker_config().lock().ok().and_then(|slot| slot.as_ref().cloned())
}

pub async fn run_local_socks_proxy(control: Control) -> Result<(), String> {
    let listener = TcpListener::bind(LOCAL_SOCKS_ADDRESS)
        .await
        .map_err(|e| format!("绑定本地账号 VPN SOCKS5 端口失败：{e}"))?;

    loop {
        let (client, address) = listener.accept().await
            .map_err(|e| format!("本地账号 VPN SOCKS5 接收失败：{e}"))?;
        if !address.ip().is_loopback() {
            drop(client);
            continue;
        }
        let stream_control = control.clone();
        tokio::spawn(async move {
            let _ = handle_socks_client(client, stream_control).await;
        });
    }
}

async fn handle_socks_client(mut client: TcpStream, mut control: Control) -> Result<(), String> {
    let Some(config) = get_worker_config() else {
        let _ = socks_reply(&mut client, 1).await;
        return Err("账号 VPN 尚未配置 Worker 主机".to_string());
    };

    // SOCKS5 username/password authentication (RFC 1929). The random password
    // exists only while the VpnService task is active.
    let mut greeting = [0u8; 2];
    client.read_exact(&mut greeting).await.map_err(|e| format!("SOCKS5 greeting: {e}"))?;
    if greeting[0] != 5 || greeting[1] == 0 || greeting[1] > 16 {
        return Err("SOCKS5 greeting was invalid".to_string());
    }
    let mut methods = vec![0u8; usize::from(greeting[1])];
    client.read_exact(&mut methods).await.map_err(|e| format!("SOCKS5 methods: {e}"))?;
    if !methods.contains(&2) {
        client.write_all(&[5, 0xff]).await.map_err(|e| e.to_string())?;
        return Err("SOCKS5 client did not offer password authentication".to_string());
    }
    client.write_all(&[5, 2]).await.map_err(|e| e.to_string())?;

    let mut auth = [0u8; 2];
    client.read_exact(&mut auth).await.map_err(|e| format!("SOCKS5 auth header: {e}"))?;
    if auth[0] != 1 || auth[1] == 0 || auth[1] > 128 {
        client.write_all(&[1, 1]).await.map_err(|e| e.to_string())?;
        return Err("SOCKS5 authentication header was invalid".to_string());
    }
    let mut username = vec![0u8; usize::from(auth[1])];
    client.read_exact(&mut username).await.map_err(|e| format!("SOCKS5 username: {e}"))?;
    let mut password_len = [0u8; 1];
    client.read_exact(&mut password_len).await.map_err(|e| format!("SOCKS5 password length: {e}"))?;
    if password_len[0] == 0 || password_len[0] > 128 {
        client.write_all(&[1, 1]).await.map_err(|e| e.to_string())?;
        return Err("SOCKS5 password length was invalid".to_string());
    }
    let mut password = vec![0u8; usize::from(password_len[0])];
    client.read_exact(&mut password).await.map_err(|e| format!("SOCKS5 password: {e}"))?;

    let expected_password = config.secret.as_bytes();
    let accepted = username == b"effectcraft"
        && password.len() == expected_password.len()
        && password.iter().zip(expected_password).fold(0u8, |acc, (a, b)| acc | (a ^ b)) == 0;
    client.write_all(&[1, if accepted { 0 } else { 1 }]).await.map_err(|e| e.to_string())?;
    if !accepted {
        return Err("SOCKS5 authentication failed".to_string());
    }

    let mut request = [0u8; 4];
    client.read_exact(&mut request).await.map_err(|e| format!("SOCKS5 request: {e}"))?;
    if request[0] != 5 || request[1] != 1 || request[2] != 0 {
        socks_reply(&mut client, 7).await?;
        return Err("Only SOCKS5 CONNECT is supported".to_string());
    }

    let requested_ip = match request[3] {
        1 => {
            let mut bytes = [0u8; 4];
            client.read_exact(&mut bytes).await.map_err(|e| format!("SOCKS5 IPv4: {e}"))?;
            Some(IpAddr::from(bytes))
        }
        4 => {
            let mut bytes = [0u8; 16];
            client.read_exact(&mut bytes).await.map_err(|e| format!("SOCKS5 IPv6: {e}"))?;
            Some(IpAddr::from(bytes))
        }
        3 => {
            let mut len = [0u8; 1];
            client.read_exact(&mut len).await.map_err(|e| format!("SOCKS5 domain length: {e}"))?;
            let mut domain = vec![0u8; usize::from(len[0])];
            client.read_exact(&mut domain).await.map_err(|e| format!("SOCKS5 domain: {e}"))?;
            let domain = String::from_utf8(domain).map_err(|_| "SOCKS5 domain was not UTF-8".to_string())?;
            if !domain.eq_ignore_ascii_case(&config.host) {
                socks_reply(&mut client, 2).await?;
                return Err("SOCKS5 domain is outside the account Worker allowlist".to_string());
            }
            None
        }
        _ => {
            socks_reply(&mut client, 8).await?;
            return Err("SOCKS5 address type is unsupported".to_string());
        }
    };

    let mut port = [0u8; 2];
    client.read_exact(&mut port).await.map_err(|e| format!("SOCKS5 port: {e}"))?;
    if u16::from_be_bytes(port) != 443 || requested_ip.is_some_and(|ip| !config.ips.contains(&ip)) {
        socks_reply(&mut client, 2).await?;
        return Err("SOCKS5 target IP/port is outside the Worker route".to_string());
    }

    let Some(admin_peer) = get_admin_peer() else {
        socks_reply(&mut client, 4).await?;
        return Err("未发现管理版出口节点".to_string());
    };

    let mut tunnel = match control.open_stream(admin_peer, StreamProtocol::new(PROTOCOL_NAME)).await {
        Ok(tunnel) => tunnel,
        Err(error) => {
            socks_reply(&mut client, 4).await?;
            return Err(format!("打开管理版加密 VPN 通道失败：{error}"));
        }
    };

    let host = config.host.as_bytes();
    if host.is_empty() || host.len() > u8::MAX as usize {
        socks_reply(&mut client, 1).await?;
        return Err("Worker 主机名长度无效".to_string());
    }
    tunnel.write_all(&[1, host.len() as u8]).await.map_err(|e| e.to_string())?;
    tunnel.write_all(host).await.map_err(|e| e.to_string())?;
    tunnel.write_all(&443u16.to_be_bytes()).await.map_err(|e| e.to_string())?;
    let mut result = [1u8; 1];
    tunnel.read_exact(&mut result).await.map_err(|e| format!("管理版 VPN 出口响应失败：{e}"))?;
    if result[0] != 0 {
        socks_reply(&mut client, 5).await?;
        return Err("管理版无法连接 Cloudflare Worker".to_string());
    }

    socks_reply(&mut client, 0).await?;
    let mut tunnel = tunnel.compat();
    tokio::io::copy_bidirectional(&mut client, &mut tunnel)
        .await
        .map_err(|e| format!("SOCKS5 与 P2P VPN 隧道转发失败：{e}"))?;
    Ok(())
}

async fn socks_reply(client: &mut TcpStream, code: u8) -> Result<(), String> {
    client.write_all(&[5, code, 0, 1, 0, 0, 0, 0, 0, 0])
        .await
        .map_err(|e| format!("SOCKS5 response: {e}"))
}
