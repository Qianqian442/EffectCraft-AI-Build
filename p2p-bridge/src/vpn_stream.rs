//! Bounded bidirectional TCP streams for EffectCraft's private account tunnel.
//!
//! This protocol is intentionally narrower than a general-purpose proxy: only DNS
//! names below workers.dev on TCP/443 are accepted. The HTTPS/TLS byte stream is
//! forwarded unchanged, so the admin phone cannot read account credentials.

use std::net::IpAddr;
use std::time::Duration;

use futures::io::{AsyncReadExt, AsyncWriteExt};
use libp2p::swarm::Stream;
use tokio::net::TcpStream;
use tokio_util::compat::FuturesAsyncReadCompatExt;

pub const PROTOCOL_NAME: &str = "/effectcraft/account-vpn-tcp/1.0.0";
const MAX_HOST_BYTES: usize = 253;
const CONNECT_TIMEOUT: Duration = Duration::from_secs(8);

pub fn is_allowed_destination(host: &str, port: u16) -> bool {
    if port != 443 || host.len() > MAX_HOST_BYTES || !host.is_ascii() {
        return false;
    }

    let host = host.to_ascii_lowercase();
    let Some(prefix) = host.strip_suffix(".workers.dev") else {
        return false;
    };

    if prefix.is_empty() || prefix.len() > 200 || prefix.starts_with('.') || prefix.ends_with('.') {
        return false;
    }

    host.split('.').all(|label| {
        !label.is_empty()
            && label.len() <= 63
            && label.bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
            && !label.starts_with('-')
            && !label.ends_with('-')
    })
}

pub fn is_public_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            !ip.is_private()
                && !ip.is_loopback()
                && !ip.is_link_local()
                && !ip.is_unspecified()
                && !ip.is_broadcast()
                && !ip.is_multicast()
        }
        IpAddr::V6(ip) => {
            !ip.is_loopback()
                && !ip.is_unspecified()
                && !ip.is_unique_local()
                && !ip.is_unicast_link_local()
                && !ip.is_multicast()
        }
    }
}

/// Handle one authenticated libp2p stream on the administrator phone.
///
/// Wire format: version:u8, host_len:u8, hostname:[u8; host_len], port:u16be.
/// Response: 0 = connected; 1 = rejected/unavailable. After a zero response,
/// the stream becomes a transparent full-duplex TLS byte pipe.
pub async fn serve_admin_stream(mut stream: Stream) -> Result<(), String> {
    let mut prefix = [0u8; 2];
    stream.read_exact(&mut prefix).await.map_err(|e| format!("VPN stream header: {e}"))?;
    if prefix[0] != 1 || prefix[1] == 0 || usize::from(prefix[1]) > MAX_HOST_BYTES {
        let _ = stream.write_all(&[1]).await;
        return Err("VPN stream header was invalid".to_string());
    }

    let mut host_bytes = vec![0u8; usize::from(prefix[1])];
    stream.read_exact(&mut host_bytes).await.map_err(|e| format!("VPN stream hostname: {e}"))?;
    let mut port_bytes = [0u8; 2];
    stream.read_exact(&mut port_bytes).await.map_err(|e| format!("VPN stream port: {e}"))?;

    let host = String::from_utf8(host_bytes).map_err(|_| "VPN hostname was not UTF-8".to_string())?;
    let port = u16::from_be_bytes(port_bytes);
    if !is_allowed_destination(&host, port) {
        let _ = stream.write_all(&[1]).await;
        return Err("VPN destination is not on the account API allowlist".to_string());
    }

    let mut addresses = tokio::net::lookup_host((host.as_str(), port))
        .await
        .map_err(|e| format!("VPN destination DNS lookup failed: {e}"))?;
    let address = addresses
        .find(|address| is_public_ip(address.ip()))
        .ok_or_else(|| "VPN destination did not resolve to a public IP".to_string())?;

    let remote = tokio::time::timeout(CONNECT_TIMEOUT, TcpStream::connect(address))
        .await
        .map_err(|_| "VPN destination connection timed out".to_string())?
        .map_err(|e| format!("VPN destination connection failed: {e}"))?;

    stream.write_all(&[0]).await.map_err(|e| format!("VPN stream ready signal: {e}"))?;
    let mut remote = remote;
    let mut tunnel = stream.compat();
    tokio::io::copy_bidirectional(&mut tunnel, &mut remote)
        .await
        .map_err(|e| format!("VPN stream forwarding failed: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_only_workers_dev_https() {
        assert!(is_allowed_destination("ae-cloud-account-api.example.workers.dev", 443));
        assert!(is_allowed_destination("AE-CLOUD-ACCOUNT-API.EXAMPLE.WORKERS.DEV", 443));
        assert!(!is_allowed_destination("example.com", 443));
        assert!(!is_allowed_destination("workers.dev", 443));
        assert!(!is_allowed_destination("evilworkers.dev", 443));
        assert!(!is_allowed_destination("a..workers.dev", 443));
        assert!(!is_allowed_destination("-bad.workers.dev", 443));
        assert!(!is_allowed_destination("bad-.workers.dev", 443));
        assert!(!is_allowed_destination("a.workers.dev", 80));
    }

    #[test]
    fn rejects_private_and_local_addresses() {
        assert!(!is_public_ip("127.0.0.1".parse().unwrap()));
        assert!(!is_public_ip("10.0.0.1".parse().unwrap()));
        assert!(!is_public_ip("192.168.1.1".parse().unwrap()));
        assert!(!is_public_ip("::1".parse().unwrap()));
        assert!(!is_public_ip("fc00::1".parse().unwrap()));
        assert!(is_public_ip("1.1.1.1".parse().unwrap()));
    }
}
