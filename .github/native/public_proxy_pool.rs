//! Dynamic public proxy pool for end-to-end TLS-tunneled Cloudflare account access.
//!
//! Public proxies are untrusted transports. HTTP CONNECT / SOCKS5 only forwards
//! bytes. The TLS/WSS session is still created by this device for the exact
//! Cloudflare Workers hostname with certificate verification enabled.

use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::time::{Duration, Instant};
use tungstenite::client::IntoClientRequest;
use tungstenite::handshake::client::Response;
use tungstenite::stream::MaybeTlsStream;
use tungstenite::{Error as WebSocketError, WebSocket};
use ureq::{Agent, Proxy};

const FEED_REFRESH: Duration = Duration::from_secs(30 * 60);
const BAD_COOLDOWN: Duration = Duration::from_secs(15 * 60);
const GOOD_TTL: Duration = Duration::from_secs(2 * 60);
const MAX_FEED_BYTES: usize = 1_000_000;
const MAX_POOL_SIZE: usize = 600;
const MAX_PER_FEED: usize = 80;
const MAX_TEST_COUNT: usize = 18;
const MAX_SCAN_TIME: Duration = Duration::from_secs(28);

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum Protocol {
    HttpConnect,
    Socks5,
}

impl Protocol {
    fn parse(value: &str) -> Option<Self> {
        match value.to_ascii_lowercase().as_str() {
            "http" => Some(Self::HttpConnect),
            "socks5" | "socks5h" => Some(Self::Socks5),
            _ => None,
        }
    }

    fn scheme(self) -> &'static str {
        match self {
            Self::HttpConnect => "http",
            Self::Socks5 => "socks5",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct Candidate {
    protocol: Protocol,
    address: SocketAddr,
}

impl Candidate {
    fn key(&self) -> String {
        format!("{}://{}", self.protocol.scheme(), self.address)
    }
}

struct Feed {
    url: &'static str,
    default_protocol: Protocol,
    prefixed: bool,
}

const FEEDS: &[Feed] = &[
    // Mainland and nearby regions first. This source prefixes each entry with its protocol.
    Feed { url: "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/cn.txt", default_protocol: Protocol::HttpConnect, prefixed: true },
    Feed { url: "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/hk.txt", default_protocol: Protocol::HttpConnect, prefixed: true },
    Feed { url: "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/jp.txt", default_protocol: Protocol::HttpConnect, prefixed: true },
    Feed { url: "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/sg.txt", default_protocol: Protocol::HttpConnect, prefixed: true },
    Feed { url: "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/https.txt", default_protocol: Protocol::HttpConnect, prefixed: true },
    Feed { url: "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/socks5.txt", default_protocol: Protocol::Socks5, prefixed: false },
    // Independent second source. These files contain bare IP:port entries, typed by their path.
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/cn/http.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/cn/https.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/cn/socks5.txt", default_protocol: Protocol::Socks5, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/hk/http.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/hk/https.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/hk/socks5.txt", default_protocol: Protocol::Socks5, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/jp/http.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/jp/https.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/jp/socks5.txt", default_protocol: Protocol::Socks5, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/sg/http.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/sg/https.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/sg/socks5.txt", default_protocol: Protocol::Socks5, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/http.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/https.txt", default_protocol: Protocol::HttpConnect, prefixed: false },
    Feed { url: "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/socks5.txt", default_protocol: Protocol::Socks5, prefixed: false },
];

#[derive(Default)]
struct PoolState {
    candidates: Vec<Candidate>,
    fetched_at: Option<Instant>,
    last_good: Option<Candidate>,
    last_good_at: Option<Instant>,
    failed_until: HashMap<String, Instant>,
    refreshing: bool,
}

static POOL: OnceLock<Mutex<PoolState>> = OnceLock::new();

fn pool() -> MutexGuard<'static, PoolState> {
    POOL.get_or_init(|| Mutex::new(PoolState::default()))
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn public_ipv4(ip: Ipv4Addr) -> bool {
    let o = ip.octets();
    if ip.is_private() || ip.is_loopback() || ip.is_link_local()
        || ip.is_broadcast() || ip.is_unspecified() || ip.is_multicast()
    {
        return false;
    }
    if o[0] == 0 || o[0] >= 224
        || (o[0] == 100 && (64..=127).contains(&o[1]))
        || (o[0] == 192 && o[1] == 0 && o[2] == 0)
        || (o[0] == 192 && o[1] == 0 && o[2] == 2)
        || (o[0] == 192 && o[1] == 88 && o[2] == 99)
        || (o[0] == 198 && (18..=19).contains(&o[1]))
        || (o[0] == 198 && o[1] == 51 && o[2] == 100)
        || (o[0] == 203 && o[1] == 0 && o[2] == 113)
    {
        return false;
    }
    true
}

fn parse_line(line: &str, default_protocol: Protocol, prefixed: bool) -> Option<Candidate> {
    let line = line.trim();
    if line.is_empty() || line.starts_with('#') || line.len() > 160 {
        return None;
    }
    let (protocol, endpoint) = if let Some((scheme, rest)) = line.split_once("://") {
        if !prefixed {
            return None;
        }
        (Protocol::parse(scheme)?, rest)
    } else {
        (default_protocol, line)
    };
    if endpoint.chars().any(|ch| matches!(ch, '@' | '/' | '?' | '#' | ' ')) {
        return None;
    }
    let address: SocketAddr = endpoint.parse().ok()?;
    let ip = match address.ip() {
        std::net::IpAddr::V4(ip) => ip,
        std::net::IpAddr::V6(_) => return None,
    };
    if !public_ipv4(ip) || address.port() == 0 {
        return None;
    }
    Some(Candidate { protocol, address })
}

fn make_agent(candidate: Option<&Candidate>, timeout: Duration) -> Result<Agent, String> {
    let mut config = Agent::config_builder()
        .http_status_as_error(false)
        .timeout_global(Some(timeout))
        .proxy(None);
    if let Some(candidate) = candidate {
        let proxy_url = format!("{}://{}", candidate.protocol.scheme(), candidate.address);
        let proxy = Proxy::new(&proxy_url).map_err(|_| "代理配置无效".to_string())?;
        config = config.proxy(Some(proxy));
    }
    Ok(config.build().into())
}

fn fetch_feed(feed: &Feed, deadline: Instant) -> Vec<Candidate> {
    if Instant::now() >= deadline {
        return Vec::new();
    }
    let remaining = deadline.saturating_duration_since(Instant::now());
    let timeout = Duration::from_millis(2500).min(remaining);
    let Ok(agent) = make_agent(None, timeout) else { return Vec::new(); };
    let Ok(mut response) = agent.get(feed.url).call() else { return Vec::new(); };
    if response.status().as_u16() != 200 {
        return Vec::new();
    }
    let Ok(body) = response.body_mut().read_to_string() else { return Vec::new(); };
    if body.len() > MAX_FEED_BYTES {
        return Vec::new();
    }
    body.lines().take(MAX_PER_FEED)
        .filter_map(|line| parse_line(line, feed.default_protocol, feed.prefixed))
        .collect()
}

fn refresh_pool() {
    let should_refresh = {
        let mut state = pool();
        if state.fetched_at.is_some_and(|at| at.elapsed() < FEED_REFRESH) || state.refreshing {
            false
        } else {
            // Use the packaged snapshot immediately on first boot.
            if state.candidates.is_empty() {
                let mut seen = HashSet::new();
                state.candidates = include_str!("public_proxy_bootstrap.txt")
                    .lines()
                    .filter_map(|line| parse_line(line, Protocol::HttpConnect, true))
                    .filter(|candidate| seen.insert(candidate.key()))
                    .take(MAX_POOL_SIZE)
                    .collect();
            }
            state.refreshing = true;
            state.fetched_at = Some(Instant::now());
            true
        }
    };
    if !should_refresh {
        return;
    }

    // Refresh feeds away from the login/request thread. Existing packaged or
    // last-known candidates remain available while this refresh runs.
    std::thread::spawn(|| {
        let deadline = Instant::now() + Duration::from_secs(20);
        let mut candidates = Vec::new();
        let mut seen = HashSet::new();

        for feed in FEEDS {
            if Instant::now() >= deadline || candidates.len() >= MAX_POOL_SIZE {
                break;
            }
            for candidate in fetch_feed(feed, deadline) {
                if seen.insert(candidate.key()) {
                    candidates.push(candidate);
                }
                if candidates.len() >= MAX_POOL_SIZE {
                    break;
                }
            }
        }

        let mut state = pool();
        if !candidates.is_empty() {
            let mut merged = Vec::new();
            let mut merged_keys = HashSet::new();
            for candidate in state.candidates.drain(..).chain(candidates.into_iter()) {
                if merged_keys.insert(candidate.key()) {
                    merged.push(candidate);
                }
                if merged.len() >= MAX_POOL_SIZE {
                    break;
                }
            }
            state.candidates = merged;
        }
        state.fetched_at = Some(Instant::now());
        state.refreshing = false;
    });
}

fn candidates_snapshot() -> Vec<Candidate> {
    refresh_pool();
    let now = Instant::now();
    let state = pool();
    let mut output = Vec::new();
    if let (Some(candidate), Some(last_good_at)) =
        (state.last_good.as_ref(), state.last_good_at)
    {
        if last_good_at.elapsed() < GOOD_TTL {
            output.push(candidate.clone());
        }
    }
    for candidate in &state.candidates {
        if output.contains(candidate) {
            continue;
        }
        let cooling = state.failed_until
            .get(&candidate.key())
            .is_some_and(|until| *until > now);
        if !cooling {
            output.push(candidate.clone());
        }
    }
    output
}

fn mark_good(candidate: &Candidate) {
    let mut state = pool();
    state.last_good = Some(candidate.clone());
    state.last_good_at = Some(Instant::now());
    state.failed_until.remove(&candidate.key());
}

fn mark_bad(candidate: &Candidate) {
    let mut state = pool();
    state.failed_until.insert(candidate.key(), Instant::now() + BAD_COOLDOWN);
    if state.last_good.as_ref() == Some(candidate) {
        state.last_good = None;
        state.last_good_at = None;
    }
}

fn healthy_worker(agent: &Agent, base_url: &str) -> bool {
    let endpoint = format!("{}/health", base_url.trim_end_matches('/'));
    let Ok(mut response) = agent.get(&endpoint).header("Accept", "application/json").call() else {
        return false;
    };
    if response.status().as_u16() != 200 {
        return false;
    }
    let Ok(body) = response.body_mut().read_to_string() else { return false; };
    let Ok(value) = serde_json::from_str::<Value>(&body) else { return false; };
    value.get("ok").and_then(Value::as_bool) == Some(true)
        && value.get("database").and_then(Value::as_bool) == Some(true)
}

fn select_http_route(base_url: &str) -> Result<(Agent, Option<Candidate>), String> {
    // Prefer direct end-to-end TLS whenever the real Worker health endpoint works.
    let direct = make_agent(None, Duration::from_secs(8))?;
    if healthy_worker(&direct, base_url) {
        return Ok((direct, None));
    }

    let deadline = Instant::now() + MAX_SCAN_TIME;
    for candidate in candidates_snapshot().into_iter().take(MAX_TEST_COUNT) {
        if Instant::now() >= deadline {
            break;
        }
        let Ok(agent) = make_agent(Some(&candidate), Duration::from_secs(3)) else {
            mark_bad(&candidate);
            continue;
        };
        if healthy_worker(&agent, base_url) {
            mark_good(&candidate);
            return Ok((agent, Some(candidate)));
        }
        mark_bad(&candidate);
    }
    Err("Cloudflare 直连失败，公开代理池没有找到通过 TLS 和账号数据库健康检查的节点。请稍后重试。".to_string())
}

/// Selects a real Cloudflare route first, then sends one account request.
/// Mutating operations are never blindly replayed after an ambiguous transport error.
pub(crate) fn account_http_request(
    base_url: &str,
    method: &str,
    path: &str,
    body: Value,
    token: Option<&str>,
) -> Result<(u16, Value), String> {
    if !base_url.starts_with("https://") || !base_url.ends_with(".workers.dev") {
        return Err("账号服务地址必须是已配置的 Cloudflare HTTPS workers.dev 地址".to_string());
    }
    if !path.starts_with("/v1/") || path.contains("..") || path.contains('#') {
        return Err("账号 API 路径无效".to_string());
    }
    if !matches!(method, "GET" | "POST") {
        return Err("账号 API 请求方法不受支持".to_string());
    }

    let (agent, route) = select_http_route(base_url)?;
    let endpoint = format!("{}{}", base_url.trim_end_matches('/'), path);
    let response_result = if method == "GET" {
        let mut request = agent
            .get(&endpoint)
            .header("Accept", "application/json");
        if let Some(token) = token {
            request = request.header("Authorization", &format!("Bearer {token}"));
        }
        request.call()
    } else {
        let bytes = if body.is_null() {
            b"{}".to_vec()
        } else {
            serde_json::to_vec(&body).map_err(|_| "账号请求数据编码失败".to_string())?
        };
        let mut request = agent
            .post(&endpoint)
            .header("Accept", "application/json")
            .header("Content-Type", "application/json");
        if let Some(token) = token {
            request = request.header("Authorization", &format!("Bearer {token}"));
        }
        request.send(bytes.as_slice())
    };
    // Never replay a submitted POST: the upstream may have committed it before
    // the transport error occurred.
    let mut response = response_result.map_err(|_| {
        if route.is_some() {
            "已通过代理连接 Cloudflare，但账号操作的响应中断；本次不会重复提交。".to_string()
        } else {
            "Cloudflare 直连操作的响应中断；本次不会重复提交。".to_string()
        }
    })?;

    let status = response.status().as_u16();
    let mut response_body = String::new();
    response.body_mut().read_to_string(&mut response_body)
        .map_err(|_| "Cloudflare 响应读取失败".to_string())?;
    let value = serde_json::from_str::<Value>(&response_body)
        .unwrap_or_else(|_| serde_json::json!({"detail": "服务器返回的数据格式无法识别"}));
    Ok((status, value))
}

fn proxy_stream(candidate: &Candidate) -> io::Result<TcpStream> {
    let mut stream = TcpStream::connect_timeout(&candidate.address, Duration::from_secs(4))?;
    stream.set_read_timeout(Some(Duration::from_secs(8)))?;
    stream.set_write_timeout(Some(Duration::from_secs(8)))?;
    stream.set_nodelay(true)?;
    Ok(stream)
}

fn http_connect(stream: &mut TcpStream, host: &str, port: u16) -> io::Result<()> {
    let authority = format!("{host}:{port}");
    write!(
        stream,
        "CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\nProxy-Connection: Keep-Alive\r\n\r\n"
    )?;
    stream.flush()?;

    let mut header = Vec::with_capacity(256);
    let mut byte = [0u8; 1];
    while header.len() < 8192 {
        stream.read_exact(&mut byte)?;
        header.push(byte[0]);
        if header.ends_with(b"\r\n\r\n") {
            break;
        }
    }
    if !header.ends_with(b"\r\n\r\n") {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "CONNECT 响应头过长"));
    }
    let text = String::from_utf8_lossy(&header);
    let status = text.lines().next().unwrap_or_default();
    if !(status.starts_with("HTTP/1.0 200 ") || status.starts_with("HTTP/1.1 200 ")) {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "代理拒绝 HTTPS CONNECT"));
    }
    Ok(())
}

fn socks5_connect(stream: &mut TcpStream, host: &str, port: u16) -> io::Result<()> {
    stream.write_all(&[0x05, 0x01, 0x00])?;
    let mut hello = [0u8; 2];
    stream.read_exact(&mut hello)?;
    if hello != [0x05, 0x00] {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "SOCKS5 不接受无认证连接"));
    }

    let name = host.as_bytes();
    if name.is_empty() || name.len() > 255 {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "Cloudflare 主机名无效"));
    }
    let mut request = vec![0x05, 0x01, 0x00, 0x03, name.len() as u8];
    request.extend_from_slice(name);
    request.extend_from_slice(&port.to_be_bytes());
    stream.write_all(&request)?;

    let mut response = [0u8; 4];
    stream.read_exact(&mut response)?;
    if response[0] != 0x05 || response[1] != 0x00 {
        return Err(io::Error::new(io::ErrorKind::ConnectionRefused, "SOCKS5 无法连接 Cloudflare"));
    }
    match response[3] {
        0x01 => {
            let mut discard = [0u8; 6];
            stream.read_exact(&mut discard)?;
        }
        0x03 => {
            let mut length = [0u8; 1];
            stream.read_exact(&mut length)?;
            let mut discard = vec![0u8; length[0] as usize + 2];
            stream.read_exact(&mut discard)?;
        }
        0x04 => {
            let mut discard = [0u8; 18];
            stream.read_exact(&mut discard)?;
        }
        _ => return Err(io::Error::new(io::ErrorKind::InvalidData, "SOCKS5 地址类型无效")),
    }
    Ok(())
}

fn open_tunnel(candidate: &Candidate, host: &str, port: u16) -> io::Result<TcpStream> {
    let mut stream = proxy_stream(candidate)?;
    match candidate.protocol {
        Protocol::HttpConnect => http_connect(&mut stream, host, port)?,
        Protocol::Socks5 => socks5_connect(&mut stream, host, port)?,
    }
    Ok(stream)
}

fn websocket_candidates(base_url: &str) -> Vec<Candidate> {
    let deadline = Instant::now() + MAX_SCAN_TIME;
    let mut healthy = Vec::new();
    for candidate in candidates_snapshot().into_iter().take(MAX_TEST_COUNT) {
        if Instant::now() >= deadline {
            break;
        }
        let Ok(agent) = make_agent(Some(&candidate), Duration::from_secs(3)) else {
            mark_bad(&candidate);
            continue;
        };
        if healthy_worker(&agent, base_url) {
            mark_good(&candidate);
            healthy.push(candidate);
        } else {
            mark_bad(&candidate);
        }
    }
    healthy
}

/// Direct WSS first; then retry multiple verified HTTP CONNECT / SOCKS5 tunnels.
/// The TLS hostname and certificate checks remain enabled for every attempt.
pub(crate) fn connect_websocket<R>(
    request: R,
) -> Result<(WebSocket<MaybeTlsStream<TcpStream>>, Response), WebSocketError>
where
    R: IntoClientRequest,
{
    let request = request.into_client_request()?;
    let direct_error = match tungstenite::connect(request.clone()) {
        Ok(connection) => return Ok(connection),
        Err(error) => {
            // A real Worker 401 means the request reached Cloudflare and the
            // credential was rejected; trying a proxy cannot repair it.
            if matches!(&error, WebSocketError::Http(response) if response.status().as_u16() == 401) {
                return Err(error);
            }
            error
        }
    };

    let host = request.uri().host().ok_or_else(|| {
        WebSocketError::Io(io::Error::new(io::ErrorKind::InvalidInput, "WSS 主机名缺失"))
    })?;
    let port = request.uri().port_u16().unwrap_or(443);
    let base_url = format!("https://{host}");
    let candidates = websocket_candidates(&base_url);
    let mut last_error = direct_error;

    for candidate in candidates {
        let mut stream = match open_tunnel(&candidate, host, port) {
            Ok(stream) => stream,
            Err(_) => {
                mark_bad(&candidate);
                continue;
            }
        };
        if stream.set_read_timeout(Some(Duration::from_secs(12))).is_err()
            || stream.set_write_timeout(Some(Duration::from_secs(12))).is_err()
        {
            mark_bad(&candidate);
            continue;
        }

        match tungstenite::client_tls_with_config(request.clone(), stream, None, None) {
            Ok((mut websocket, response)) => {
                // The 12-second socket timeout is for the TLS/WebSocket handshake
                // only. A long-lived WSS listener must not be killed while idle.
                match websocket.get_mut() {
                    MaybeTlsStream::Rustls(tls) => {
                        let _ = tls.sock.set_read_timeout(None);
                        let _ = tls.sock.set_write_timeout(Some(Duration::from_secs(30)));
                    }
                    MaybeTlsStream::Plain(socket) => {
                        let _ = socket.set_read_timeout(None);
                        let _ = socket.set_write_timeout(Some(Duration::from_secs(30)));
                    }
                    _ => {}
                }
                mark_good(&candidate);
                return Ok((websocket, response));
            }
            Err(tungstenite::HandshakeError::Failure(error)) => {
                if matches!(&error, WebSocketError::Http(response) if response.status().as_u16() == 401) {
                    return Err(error);
                }
                last_error = error;
                mark_bad(&candidate);
            }
            Err(tungstenite::HandshakeError::Interrupted(_)) => {
                last_error = WebSocketError::Io(io::Error::new(
                    io::ErrorKind::Other,
                    "WSS 代理握手未完成",
                ));
                mark_bad(&candidate);
            }
        }
    }

    Err(last_error)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_only_public_ip_and_supported_tunnels() {
        assert!(parse_line("http://1.1.1.1:8080", Protocol::Socks5, true).is_some());
        assert!(parse_line("socks5://8.8.8.8:1080", Protocol::HttpConnect, true).is_some());
        assert!(parse_line("127.0.0.1:8080", Protocol::HttpConnect, false).is_none());
        assert!(parse_line("192.168.1.2:8080", Protocol::HttpConnect, false).is_none());
        assert!(parse_line("203.0.113.10:8080", Protocol::HttpConnect, false).is_none());
        assert!(parse_line("https://1.1.1.1:8443", Protocol::HttpConnect, true).is_none());
        assert!(parse_line("socks4://1.1.1.1:1080", Protocol::HttpConnect, true).is_none());
        assert!(parse_line("user:pass@1.1.1.1:8080", Protocol::HttpConnect, false).is_none());
    }
}
