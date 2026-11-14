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
	for _, endpoint := range endpoints {
		if cfg.UseHTTP2 {
			if _, ok := endpoint.(*net.TCPAddr); !ok {
				log.Printf("MaintainTunnel: HTTP/2 endpoint must be *net.TCPAddr, got %T", endpoint)
				return
			}
		} else if _, ok := endpoint.(*net.UDPAddr); !ok {
			log.Printf("MaintainTunnel: HTTP/3 endpoint must be *net.UDPAddr, got %T", endpoint)
			return
		}
	}
	endpointIndex := 0
	endpoint := endpoints[endpointIndex]
	advanceEndpoint := func() {
		endpointIndex = (endpointIndex + 1) % len(endpoints)
		endpoint = endpoints[endpointIndex]
	}

	packetBufferPool := NewNetBuffer(cfg.MTU + datagramContextIDHeadroom)
'''
if source.count(old) != 1:
    raise SystemExit("MaintainTunnel initialization anchor mismatch")
source = source.replace(old, new, 1)
source = source.replace('log.Printf("Establishing MASQUE connection to %s", cfg.Endpoint)', 'log.Printf("Establishing MASQUE connection to %s", endpoint)')
if source.count('\t\t\tcfg.Endpoint,\n\t\t\tcfg.UseHTTP2,\n') != 1:
    raise SystemExit("ConnectTunnel endpoint argument anchor mismatch")
source = source.replace('\t\t\tcfg.Endpoint,\n\t\t\tcfg.UseHTTP2,\n', '\t\t\tendpoint,\n\t\t\tcfg.UseHTTP2,\n', 1)
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
print("Patched upstream usque for Android TUN descriptors, callbacks and endpoint failover.")
