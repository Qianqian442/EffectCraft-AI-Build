#!/usr/bin/env python3
from __future__ import annotations
import os
from pathlib import Path

root = Path(os.environ["USQUE_SOURCE_DIR"]).resolve()
path = root / "api/tunnel.go"
source = path.read_text(encoding="utf-8")
for line in [
    '\t"github.com/songgao/water"\n',
    '\t"golang.zx2c4.com/wireguard/tun"\n',
]:
    if line not in source:
        raise SystemExit(f"expected upstream import missing: {line.strip()}")
    source = source.replace(line, "", 1)

start = source.find("// NetstackAdapter wraps")
end = source.find("// pumpShutdownGrace")
if start < 0 or end < 0 or start >= end:
    raise SystemExit("platform-specific TUN adapter block not found")
source = source[:start] + source[end:]

old = '\tHookEnv map[string]string\n'
new = (
    '\tHookEnv           map[string]string\n'
    '\tEndpoints         []net.Addr\n'
    '\tOnConnected       func(net.Addr)\n'
    '\tOnConnectError    func(net.Addr, error)\n'
    '\tOnDisconnected    func(net.Addr, error)\n'
)
if source.count(old) != 1:
    raise SystemExit("MaintainTunnelConfig HookEnv anchor mismatch")
source = source.replace(old, new, 1)

old = '''func MaintainTunnel(ctx context.Context, cfg MaintainTunnelConfig) {
	if cfg.UseHTTP2 {
		if _, ok := cfg.Endpoint.(*net.TCPAddr); !ok {
			log.Fatalf("MaintainTunnel: HTTP/2 mode requires a *net.TCPAddr endpoint, got %T", cfg.Endpoint)
		}
	} else {
		if _, ok := cfg.Endpoint.(*net.UDPAddr); !ok {
			log.Fatalf("MaintainTunnel: HTTP/3 mode requires a *net.UDPAddr endpoint, got %T", cfg.Endpoint)
		}
	}

	packetBufferPool := NewNetBuffer(cfg.MTU + datagramContextIDHeadroom)
'''
new = '''func MaintainTunnel(ctx context.Context, cfg MaintainTunnelConfig) {
	endpoints := cfg.Endpoints
	if len(endpoints) == 0 && cfg.Endpoint != nil {
		endpoints = []net.Addr{cfg.Endpoint}
	}
	if len(endpoints) == 0 {
		log.Println("MaintainTunnel: no MASQUE endpoints configured")
		return
	}
	for _, candidate := range endpoints {
		switch candidate.(type) {
		case *net.TCPAddr, *net.UDPAddr:
		default:
			log.Printf("MaintainTunnel: unsupported MASQUE endpoint type %T", candidate)
			return
		}
	}
	endpointIndex := 0
	endpoint := endpoints[endpointIndex]
	useHTTP2 := false
	if _, ok := endpoint.(*net.TCPAddr); ok { useHTTP2 = true }
	advanceEndpoint := func() {
		endpointIndex = (endpointIndex + 1) % len(endpoints)
		endpoint = endpoints[endpointIndex]
		_, useHTTP2 = endpoint.(*net.TCPAddr)
	}

	packetBufferPool := NewNetBuffer(cfg.MTU + datagramContextIDHeadroom)
'''
if source.count(old) != 1:
    raise SystemExit("MaintainTunnel initialization anchor mismatch")
source = source.replace(old, new, 1)
source = source.replace('log.Printf("Establishing MASQUE connection to %s", cfg.Endpoint)', 'log.Printf("Establishing MASQUE connection to %s", endpoint)')
if source.count('\t\t\tcfg.Endpoint,\n\t\t\tcfg.UseHTTP2,\n') != 1:
    raise SystemExit("ConnectTunnel endpoint argument anchor mismatch")
source = source.replace('\t\t\tcfg.Endpoint,\n\t\t\tcfg.UseHTTP2,\n', '\t\t\tendpoint,\n\t\t\tuseHTTP2,\n', 1)

# Give every Cloudflare endpoint a bounded handshake window. The context is
# retained after success and cancelled only when the connection fails or stops.
if '\tvar activeAttemptCancel context.CancelFunc\n' not in source:
    source = source.replace(
        '\tpacketBufferPool := NewNetBuffer(cfg.MTU + datagramContextIDHeadroom)\n',
        '\tpacketBufferPool := NewNetBuffer(cfg.MTU + datagramContextIDHeadroom)\n\tvar activeAttemptCancel context.CancelFunc\n',
        1,
    )
old_connect = '''\t\tudpConn, tr, ipConn, rsp, err := ConnectTunnel(
\t\t\tctx,
\t\t\tcfg.TLSConfig,
\t\t\tinternal.DefaultQuicConfig(cfg.KeepalivePeriod, cfg.InitialPacketSize),
\t\t\tinternal.ConnectURI,
\t\t\tendpoint,
\t\t\tuseHTTP2,
\t\t)
'''
new_connect = '''\t\tattemptCtx, attemptCancel := context.WithCancel(ctx)
\t\tattemptTimer := time.AfterFunc(4*time.Second, attemptCancel)
\t\tudpConn, tr, ipConn, rsp, err := ConnectTunnel(
\t\t\tattemptCtx,
\t\t\tcfg.TLSConfig,
\t\t\tinternal.DefaultQuicConfig(cfg.KeepalivePeriod, cfg.InitialPacketSize),
\t\t\tinternal.ConnectURI,
\t\t\tendpoint,
\t\t\tuseHTTP2,
\t\t)
\t\tattemptExpired := attemptCtx.Err() != nil
\t\tattemptTimer.Stop()
\t\tif attemptExpired && err == nil {
\t\t\terr = errors.New("MASQUE endpoint handshake exceeded the 4-second attempt limit")
\t\t}
'''
if source.count(old_connect) != 1:
    raise SystemExit("ConnectTunnel call block mismatch while adding bounded attempt")
source = source.replace(old_connect, new_connect, 1)
if source.count('log.Printf("Failed to connect tunnel via %s: %v", endpoint, err)') != 1:
    raise SystemExit("ConnectTunnel error callback anchor mismatch")
source = source.replace(
    'log.Printf("Failed to connect tunnel via %s: %v", endpoint, err)',
    'attemptCancel()\n\t\t\tlog.Printf("Failed to connect tunnel via %s: %v", endpoint, err)',
    1,
)
if source.count('connectErr := fmt.Errorf("MASQUE endpoint %s returned %s", endpoint, rsp.Status)') != 1:
    raise SystemExit("MASQUE non-200 response anchor mismatch")
source = source.replace(
    'connectErr := fmt.Errorf("MASQUE endpoint %s returned %s", endpoint, rsp.Status)',
    'attemptCancel()\n\t\t\tconnectErr := fmt.Errorf("MASQUE endpoint %s returned %s", endpoint, rsp.Status)',
    1,
)
source = source.replace(
    'log.Printf("Connected to MASQUE server via %s", endpoint)',
    'activeAttemptCancel = attemptCancel\n\t\tlog.Printf("Connected to MASQUE server via %s", endpoint)',
    1,
)
source = source.replace(
    '\t\t_ = ipConn.Close()\n\n\t\tdone := make(chan struct{})',
    '\t\t_ = ipConn.Close()\n\t\tif activeAttemptCancel != nil {\n\t\t\tactiveAttemptCancel()\n\t\t\tactiveAttemptCancel = nil\n\t\t}\n\n\t\tdone := make(chan struct{})',
    1,
)
source = source.replace('''			log.Printf("Failed to connect tunnel: %v", err)
			if ipConn != nil {''','''			log.Printf("Failed to connect tunnel via %s: %v", endpoint, err)
			if cfg.OnConnectError != nil { cfg.OnConnectError(endpoint, err) }
			advanceEndpoint()
			if ipConn != nil {''',1)
source = source.replace('''			log.Printf("Tunnel connection failed: %s", rsp.Status)
			_ = ipConn.Close()''','''			connectErr := fmt.Errorf("MASQUE endpoint %s returned %s", endpoint, rsp.Status)
			log.Printf("Tunnel connection failed: %s", connectErr)
			if cfg.OnConnectError != nil { cfg.OnConnectError(endpoint, connectErr) }
			advanceEndpoint()
			_ = ipConn.Close()''',1)
source = source.replace('''		log.Println("Connected to MASQUE server")

		if cfg.OnConnect != "" {''','''		log.Printf("Connected to MASQUE server via %s", endpoint)
		if cfg.OnConnected != nil { cfg.OnConnected(endpoint) }

		if cfg.OnConnect != "" {''',1)
source = source.replace('env["USQUE_ENDPOINT"] = cfg.Endpoint.String()', 'env["USQUE_ENDPOINT"] = endpoint.String()')
if source.count('\t\t\t\t\tif cfg.UseHTTP2 {') != 1:
    raise SystemExit("HTTP/2 packet-read branch anchor mismatch")
source = source.replace('\t\t\t\t\tif cfg.UseHTTP2 {', '\t\t\t\t\tif useHTTP2 {', 1)
source = source.replace('''		err = <-errChan
		log.Printf("Tunnel connection lost: %v. Reconnecting...", err)
''','''		err = <-errChan
		log.Printf("Tunnel connection lost via %s: %v. Reconnecting...", endpoint, err)
		if cfg.OnDisconnected != nil { cfg.OnDisconnected(endpoint, err) }
		advanceEndpoint()
''',1)
if "cfg.Endpoint.String()" in source:
    raise SystemExit("stale cfg.Endpoint reference")
path.write_text(source, encoding="utf-8")

# Cloudflare MASQUE uses direct HTTP/2 over TCP where available. Never use a
# system or environment HTTP proxy for the tunnel's underlay.
masque_path = root / "api/masque.go"
masque_source = masque_path.read_text(encoding="utf-8")
if '\t"time"\n' not in masque_source:
    masque_source = masque_source.replace('\t"strings"\n', '\t"strings"\n\t"time"\n', 1)
proxy_line = '\tproxyURL, _ := http.ProxyFromEnvironment(&http.Request{URL: parsedURI})'
if masque_source.count(proxy_line) != 1:
    raise SystemExit("HTTP/2 MASQUE proxy selection anchor mismatch")
masque_source = masque_source.replace(
    proxy_line,
    '\tvar proxyURL *url.URL // Direct Cloudflare underlay only; no proxy or relay.',
    1,
)
dialer_line = 'dialer := &net.Dialer{}'
if masque_source.count(dialer_line) < 1:
    raise SystemExit("HTTP/2 MASQUE dialer anchor missing")
masque_source = masque_source.replace(
    dialer_line,
    'dialer := &net.Dialer{Timeout: 5 * time.Second, KeepAlive: 15 * time.Second}',
)
handshake_line = 'if err := tlsConn.HandshakeContext(ctx); err != nil {'
if masque_source.count(handshake_line) < 1:
    raise SystemExit("HTTP/2 MASQUE TLS handshake anchor missing")
masque_source = masque_source.replace(
    handshake_line,
    'handshakeCtx, handshakeCancel := context.WithTimeout(ctx, 5*time.Second)\n'
    '\t\t\t\tif err := tlsConn.HandshakeContext(handshakeCtx); err != nil {\n'
    '\t\t\t\t\thandshakeCancel()',
)
masque_source = masque_source.replace(
    '\t\t\t\treturn tlsConn, nil',
    '\t\t\t\thandshakeCancel()\n\t\t\t\treturn tlsConn, nil',
)
masque_path.write_text(masque_source, encoding="utf-8")
print("Patched upstream usque for Android TUN, direct H2, bounded attempts and endpoint failover.")
