package warpandroid

import (
	"context"
	"crypto/ecdsa"
	"crypto/rand"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/Diniboy1123/usque/api"
	"github.com/Diniboy1123/usque/config"
)


// generateClientCert mirrors the small upstream usque self-signed client
// certificate helper without importing its Go-internal package. Server
// authentication remains pinned by api.PrepareTlsConfig below.
func generateClientCert(privKey *ecdsa.PrivateKey) ([][]byte, error) {
	now := time.Now()
	cert, err := x509.CreateCertificate(rand.Reader, &x509.Certificate{
		SerialNumber: big.NewInt(0),
		NotBefore: now,
		NotAfter: now.Add(24 * time.Hour),
	}, &x509.Certificate{}, &privKey.PublicKey, privKey)
	if err != nil {
		return nil, err
	}
	return [][]byte{cert}, nil
}

type tunDevice struct{ file *os.File }
func (d *tunDevice) ReadPacket(buf []byte) (int, error) { return d.file.Read(buf) }
func (d *tunDevice) WritePacket(packet []byte) error { _, err := d.file.Write(packet); return err }

type tunnelSession struct {
	cancel context.CancelFunc
	device *tunDevice
	done chan struct{}
	active bool
}

var (
	mu sync.Mutex
	session *tunnelSession
	state = "disconnected"
	lastError = ""
)

// StartTunnel takes ownership of the detached Android VpnService TUN fd.
// endpointList must contain Cloudflare-provided MASQUE IP:UDP-port values separated by ';'.
func StartTunnel(configJSON string, tunFD int64, endpointList string, sni string) error {
	mu.Lock()
	defer mu.Unlock()

	if session != nil && session.active { return errors.New("MASQUE tunnel is already active") }
	if tunFD < 0 { return errors.New("invalid Android TUN file descriptor") }
	if strings.TrimSpace(sni) == "" { return errors.New("Cloudflare MASQUE SNI is required") }

	var cfg config.Config
	if err := json.Unmarshal([]byte(configJSON), &cfg); err != nil { return fmt.Errorf("invalid WARP device config: %w", err) }
	if cfg.PrivateKey == "" || cfg.EndpointPubKey == "" || cfg.IPv4 == "" {
		return errors.New("WARP config missing private key, pinned endpoint key or assigned IPv4")
	}
	// Upstream usque's key parsing helpers read config.AppConfig internally.
	// Set the parsed per-device config before invoking those helpers.
	config.AppConfig = cfg
	config.ConfigLoaded = true
	endpoints, err := parseEndpoints(endpointList)
	if err != nil { return err }

	privKey, err := cfg.GetEcPrivateKey()
	if err != nil { return fmt.Errorf("WARP private key: %w", err) }
	endpointPubKey, err := cfg.GetEcEndpointPublicKey()
	if err != nil { return fmt.Errorf("Cloudflare endpoint public key: %w", err) }
	cert, err := generateClientCert(privKey)
	if err != nil { return fmt.Errorf("create MASQUE client certificate: %w", err) }
	tlsConfig, err := api.PrepareTlsConfig(privKey, endpointPubKey, cert, sni, false)
	if err != nil { return fmt.Errorf("prepare pinned MASQUE TLS: %w", err) }

	file := os.NewFile(uintptr(tunFD), "effectcraft-android-tun")
	if file == nil { return errors.New("could not take ownership of Android TUN descriptor") }
	device := &tunDevice{file: file}
	ctx, cancel := context.WithCancel(context.Background())
	current := &tunnelSession{cancel: cancel, device: device, done: make(chan struct{}), active: true}
	session = current
	state, lastError = "connecting", ""

	go func() {
		defer close(current.done)
		api.MaintainTunnel(ctx, api.MaintainTunnelConfig{
			TLSConfig: tlsConfig,
			KeepalivePeriod: 30 * time.Second,
			Endpoint: endpoints[0],
			Endpoints: endpoints,
			Device: device,
			MTU: 1280,
			ReconnectDelay: 3 * time.Second,
			AlwaysReconnect: true,
			UseHTTP2: false,
			OnConnected: func(endpoint net.Addr) {
				mu.Lock()
				if session == current && current.active { state, lastError = "connected", "" }
				mu.Unlock()
			},
			OnConnectError: func(endpoint net.Addr, connectErr error) {
				mu.Lock()
				if session == current && current.active { state, lastError = "retrying", connectErr.Error() }
				mu.Unlock()
			},
			OnDisconnected: func(endpoint net.Addr, disconnectErr error) {
				mu.Lock()
				if session == current && current.active { state, lastError = "retrying", disconnectErr.Error() }
				mu.Unlock()
			},
		})
		mu.Lock()
		if session == current && current.active { current.active = false; state = "disconnected" }
		mu.Unlock()
	}()
	return nil
}

func parseEndpoints(value string) ([]net.Addr, error) {
	parts := strings.Split(value, ";")
	endpoints := make([]net.Addr, 0, len(parts))
	seen := make(map[string]bool)
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" { continue }
		host, portText, err := net.SplitHostPort(part)
		if err != nil { return nil, fmt.Errorf("invalid MASQUE endpoint %q: %w", part, err) }
		ip := net.ParseIP(host)
		if ip == nil { return nil, fmt.Errorf("MASQUE endpoint must be a supplied numeric IP: %q", host) }
		port, err := strconv.Atoi(portText)
		if err != nil || port < 1 || port > 65535 { return nil, fmt.Errorf("invalid MASQUE endpoint port: %q", portText) }
		key := net.JoinHostPort(ip.String(), strconv.Itoa(port))
		if seen[key] { continue }
		seen[key] = true
		endpoints = append(endpoints, &net.UDPAddr{IP: ip, Port: port})
	}
	if len(endpoints) == 0 { return nil, errors.New("Cloudflare supplied no MASQUE endpoints") }
	if len(endpoints) > 16 { endpoints = endpoints[:16] }
	return endpoints, nil
}

// StopTunnel cancels the MASQUE tunnel and closes its detached Android TUN fd.
func StopTunnel() {
	mu.Lock()
	current := session
	if current == nil || !current.active { state = "disconnected"; mu.Unlock(); return }
	current.active = false
	state = "stopping"
	current.cancel()
	_ = current.device.file.Close()
	done := current.done
	mu.Unlock()

	select { case <-done: case <-time.After(3 * time.Second): }
	mu.Lock()
	if session == current { session = nil }
	state, lastError = "disconnected", ""
	mu.Unlock()
}

func State() string { mu.Lock(); defer mu.Unlock(); return state }
func LastError() string { mu.Lock(); defer mu.Unlock(); return lastError }
