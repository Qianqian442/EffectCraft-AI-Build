#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

root = Path(os.environ["USQUE_SOURCE_DIR"]).resolve()
path = root / "api/tunnel.go"
source = path.read_text(encoding="utf-8")

for line in (
    '\t"github.com/songgao/water"\n',
    '\t"golang.zx2c4.com/wireguard/tun"\n',
):
    if line not in source:
        raise SystemExit(f"expected upstream import missing: {line.strip()}")
    source = source.replace(line, "", 1)

start = source.find("// NetstackAdapter wraps")
end = source.find("// pumpShutdownGrace")
if start < 0 or end < 0 or start >= end:
    raise SystemExit("platform-specific TUN adapter block not found")
source = source[:start] + source[end:]

type_anchor = "// MaintainTunnelConfig contains runtime settings for tunnel maintenance.\n"
type_block = """// TunnelEndpoint describes one MASQUE endpoint and its transport.
type TunnelEndpoint struct {
	Address net.Addr
	UseHTTP2 bool
}

"""
if source.count(type_anchor) != 1:
    raise SystemExit("MaintainTunnelConfig type anchor mismatch")
source = source.replace(type_anchor, type_block + type_anchor, 1)

old = (
    '\tHookEnv map[string]string\n'
)
new = (
    '\tHookEnv           map[string]string\n'
    '\tEndpoints         []TunnelEndpoint\n'
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
		endpoints = []TunnelEndpoint{{Address: cfg.Endpoint, UseHTTP2: cfg.UseHTTP2}}
	}
	if len(endpoints) == 0 {
		log.Println("MaintainTunnel: no MASQUE endpoints configured")
		return
	}
	for _, candidate := range endpoints {
		if candidate.Address == nil {
			log.Println("MaintainTunnel: MASQUE endpoint address is missing")
			return
		}
		if candidate.UseHTTP2 {
			if _, ok := candidate.Address.(*net.TCPAddr); !ok {
				log.Printf("MaintainTunnel: HTTP/2 endpoint must be *net.TCPAddr, got %T", candidate.Address)
				return
			}
		} else if _, ok := candidate.Address.(*net.UDPAddr); !ok {
			log.Printf("MaintainTunnel: HTTP/3 endpoint must be *net.UDPAddr, got %T", candidate.Address)
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
source = source.replace(
    'log.Printf("Establishing MASQUE connection to %s", cfg.Endpoint)',
    'log.Printf("Establishing MASQUE connection to %s (HTTP/2=%t)", endpoint.Address, endpoint.UseHTTP2)',
    1,
)

old = '''			cfg.Endpoint,
			cfg.UseHTTP2,
'''
if source.count(old) != 1:
    raise SystemExit("ConnectTunnel endpoint arguments anchor mismatch")
source = source.replace(old, '''			endpoint.Address,
			endpoint.UseHTTP2,
''', 1)

old = '''			log.Printf("Failed to connect tunnel: %v", err)
			if ipConn != nil {'''
new = '''			log.Printf("Failed to connect tunnel via %s: %v", endpoint.Address, err)
			if cfg.OnConnectError != nil { cfg.OnConnectError(endpoint.Address, err) }
			advanceEndpoint()
			if ipConn != nil {'''
if source.count(old) != 1:
    raise SystemExit("ConnectTunnel failure callback anchor mismatch")
source = source.replace(old, new, 1)

old = '''			log.Printf("Tunnel connection failed: %s", rsp.Status)
			_ = ipConn.Close()'''
new = '''			connectErr := fmt.Errorf("MASQUE endpoint %s returned %s", endpoint.Address, rsp.Status)
			log.Printf("Tunnel connection failed: %s", connectErr)
			if cfg.OnConnectError != nil { cfg.OnConnectError(endpoint.Address, connectErr) }
			advanceEndpoint()
			_ = ipConn.Close()'''
if source.count(old) != 1:
    raise SystemExit("MASQUE non-200 callback anchor mismatch")
source = source.replace(old, new, 1)

old = '''		log.Println("Connected to MASQUE server")

		if cfg.OnConnect != "" {'''
new = '''		log.Printf("Connected to MASQUE server via %s", endpoint.Address)
		if cfg.OnConnected != nil { cfg.OnConnected(endpoint.Address) }

		if cfg.OnConnect != "" {'''
if source.count(old) != 1:
    raise SystemExit("MASQUE connected callback anchor mismatch")
source = source.replace(old, new, 1)

source = source.replace('env["USQUE_ENDPOINT"] = cfg.Endpoint.String()', 'env["USQUE_ENDPOINT"] = endpoint.Address.String()')
source = source.replace('''					if cfg.UseHTTP2 {''', '''					if endpoint.UseHTTP2 {''', 1)
source = source.replace('''		log.Printf("Tunnel connection lost: %v. Reconnecting...", err)

		if cfg.OnDisconnect != "" {''','''		log.Printf("Tunnel connection lost via %s: %v. Reconnecting...", endpoint.Address, err)
		if cfg.OnDisconnected != nil { cfg.OnDisconnected(endpoint.Address, err) }
		advanceEndpoint()

		if cfg.OnDisconnect != "" {''',1)
source = source.replace('env["USQUE_ENDPOINT"] = cfg.Endpoint.String()', 'env["USQUE_ENDPOINT"] = endpoint.Address.String()')

if "cfg.Endpoint.String()" in source or "cfg.UseHTTP2 {" in source:
    raise SystemExit("stale single-endpoint transport reference remains")
if source.count("Endpoints         []TunnelEndpoint") != 1:
    raise SystemExit("mixed-transport endpoint field was not installed")
path.write_text(source, encoding="utf-8")
print("Patched usque for Android TUN descriptors, UDP MASQUE with TCP/HTTP2 fallback, endpoint failover and state callbacks.")
