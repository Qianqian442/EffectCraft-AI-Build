package warpandroid

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/Diniboy1123/usque/api"
	"github.com/Diniboy1123/usque/config"
	"github.com/Diniboy1123/usque/internal"
)

type tunDevice struct{ file *os.File }

func (d *tunDevice) ReadPacket(buf []byte) (int, error) {
	return d.file.Read(buf)
}

func (d *tunDevice) WritePacket(packet []byte) error {
	_, err := d.file.Write(packet)
	return err
}

type tunnelSession struct {
	cancel context.CancelFunc
	device *tunDevice
	done   chan struct{}
	active bool
}

type deviceBundle struct {
	ConfigJSON string `json:"config_json"`
	Endpoints  string `json:"endpoints"`
	SNI        string `json:"sni"`
}

var (
	mu        sync.Mutex
	session   *tunnelSession
	state     = "disconnected"
	lastError = ""
)

// RegisterDevice enrolls a unique MASQUE identity for this Android installation.
// The caller must obtain the user's explicit Cloudflare Terms consent before calling it.
// The returned JSON must be stored encrypted with Android Keystore protection.
func RegisterDevice() (string, error) {
	account, err := api.Register("Android", internal.DefaultLocale, "", true)
	if err != nil {
		return "", fmt.Errorf("Cloudflare WARP device registration failed: %w", err)
	}

	privateKey, publicKey, err := internal.GenerateEcKeyPair()
	if err != nil {
		return "", fmt.Errorf("generate per-device MASQUE key failed: %w", err)
	}

	enrolled, err := api.EnrollKey(account.ID, account.Token, publicKey, "EffectCraft Android")
	if err != nil {
		return "", fmt.Errorf("Cloudflare MASQUE key enrollment failed: %w", err)
	}
	if len(enrolled.Config.Peers) == 0 {
		return "", errors.New("Cloudflare returned no MASQUE peer endpoint")
	}

	firstPeer := enrolled.Config.Peers[0]
	if firstPeer.PublicKey == "" || enrolled.Config.Interface.Addresses.V4 == "" {
		return "", errors.New("Cloudflare MASQUE response is missing its pinned key or assigned IPv4")
	}

	cfg := config.Config{
		PrivateKey:     base64.StdEncoding.EncodeToString(privateKey),
		EndpointPubKey: firstPeer.PublicKey,
		ID:             enrolled.ID,
		AccessToken:    account.Token,
		IPv4:           enrolled.Config.Interface.Addresses.V4,
		IPv6:           enrolled.Config.Interface.Addresses.V6,
		EndpointH2V4:   config.DefaultEndpointH2V4,
		EndpointH2V6:   config.DefaultEndpointH2V6,
	}
	if ip, ipErr := endpointIP(firstPeer.Endpoint.V4); ipErr == nil {
		cfg.EndpointV4 = ip.String()
	}
	if ip, ipErr := endpointIP(firstPeer.Endpoint.V6); ipErr == nil {
		cfg.EndpointV6 = ip.String()
	}

	endpointSet := make([]string, 0, 16)
	seen := make(map[string]bool)
	for _, peer := range enrolled.Config.Peers {
		// The TLS pin belongs to the selected MASQUE peer key. Never rotate to
		// an endpoint advertising a different public key without its own pin.
		if peer.PublicKey != firstPeer.PublicKey {
			continue
		}
		ips := make([]net.IP, 0, 2)
		if ip, ipErr := endpointIP(peer.Endpoint.V4); ipErr == nil {
			ips = append(ips, ip)
		}
		if ip, ipErr := endpointIP(peer.Endpoint.V6); ipErr == nil {
			ips = append(ips, ip)
		}
		for _, ip := range ips {
			for _, port := range peer.Endpoint.Ports {
				if port < 1 || port > 65535 {
					continue
				}
				value := "udp://" + net.JoinHostPort(ip.String(), strconv.Itoa(port))
				if !seen[value] {
					seen[value] = true
					endpointSet = append(endpointSet, value)
				}
				if len(endpointSet) >= 14 {
					break
				}
			}
		}
		if len(endpointSet) >= 14 {
			break
		}
	}
	if len(endpointSet) == 0 {
		return "", errors.New("Cloudflare did not return any usable MASQUE UDP endpoint/port")
	}

	// Cloudflare's documented WARP HTTP/2 endpoint is a TCP fallback for networks
	// where UDP/QUIC is blocked. It is not routed into the TUN interface.
	h2IP := cfg.EndpointH2V4
	if net.ParseIP(h2IP) == nil {
		return "", errors.New("Cloudflare HTTP/2 fallback endpoint is invalid")
	}
	h2 := "tcp://" + net.JoinHostPort(h2IP, "443")
	if !seen[h2] {
		endpointSet = append(endpointSet, h2)
	}

	configBytes, err := json.Marshal(cfg)
	if err != nil {
		return "", fmt.Errorf("encode WARP device config failed: %w", err)
	}
	bundle, err := json.Marshal(deviceBundle{
		ConfigJSON: string(configBytes),
		Endpoints:  strings.Join(endpointSet, ";"),
		SNI:        internal.ConnectSNI,
	})
	if err != nil {
		return "", fmt.Errorf("encode WARP connection bundle failed: %w", err)
	}
	return string(bundle), nil
}

func endpointIP(raw string) (net.IP, error) {
	value := strings.TrimSpace(raw)
	if value == "" {
		return nil, errors.New("empty endpoint")
	}
	if host, _, err := net.SplitHostPort(value); err == nil {
		value = strings.Trim(host, "[]")
	} else {
		value = strings.Trim(value, "[]")
	}
	ip := net.ParseIP(value)
	if ip == nil {
		return nil, fmt.Errorf("endpoint is not a numeric IP: %q", raw)
	}
	return ip, nil
}

// StartTunnel takes ownership of the detached Android VpnService TUN fd.
// Endpoints use udp://IP:port for MASQUE/HTTP3 and tcp://IP:port for HTTP/2.
func StartTunnel(bundleJSON string, tunFD int64) error {
	mu.Lock()
	defer mu.Unlock()

	if session != nil && session.active {
		return errors.New("MASQUE tunnel is already active")
	}
	if tunFD < 0 {
		return errors.New("invalid Android TUN file descriptor")
	}

	var bundle deviceBundle
	if err := json.Unmarshal([]byte(bundleJSON), &bundle); err != nil {
		return fmt.Errorf("invalid WARP connection bundle: %w", err)
	}
	if bundle.ConfigJSON == "" || strings.TrimSpace(bundle.SNI) == "" {
		return errors.New("WARP connection bundle is incomplete")
	}

	var cfg config.Config
	if err := json.Unmarshal([]byte(bundle.ConfigJSON), &cfg); err != nil {
		return fmt.Errorf("invalid WARP device config: %w", err)
	}
	if cfg.PrivateKey == "" || cfg.EndpointPubKey == "" || cfg.IPv4 == "" {
		return errors.New("WARP config missing private key, pinned endpoint key or assigned IPv4")
	}
	// usque's key helpers read config.AppConfig internally; populate it first.
	config.AppConfig = cfg
	config.ConfigLoaded = true

	endpoints, err := parseEndpoints(bundle.Endpoints)
	if err != nil {
		return err
	}
	privKey, err := cfg.GetEcPrivateKey()
	if err != nil {
		return fmt.Errorf("WARP private key: %w", err)
	}
	endpointPubKey, err := cfg.GetEcEndpointPublicKey()
	if err != nil {
		return fmt.Errorf("Cloudflare endpoint public key: %w", err)
	}
	cert, err := internal.GenerateCert(privKey, &privKey.PublicKey)
	if err != nil {
		return fmt.Errorf("create MASQUE client certificate: %w", err)
	}
	tlsConfig, err := api.PrepareTlsConfig(privKey, endpointPubKey, cert, bundle.SNI, false)
	if err != nil {
		return fmt.Errorf("prepare pinned MASQUE TLS: %w", err)
	}

	file := os.NewFile(uintptr(tunFD), "effectcraft-android-tun")
	if file == nil {
		return errors.New("could not take ownership of Android TUN descriptor")
	}
	device := &tunDevice{file: file}
	ctx, cancel := context.WithCancel(context.Background())
	current := &tunnelSession{
		cancel: cancel,
		device: device,
		done:   make(chan struct{}),
		active: true,
	}
	session = current
	state, lastError = "connecting", ""

	go func() {
		defer close(current.done)
		api.MaintainTunnel(ctx, api.MaintainTunnelConfig{
			TLSConfig:       tlsConfig,
			KeepalivePeriod: 20 * time.Second,
			Endpoint:        endpoints[0].Address,
			Endpoints:       endpoints,
			Device:          device,
			MTU:             1280,
			ReconnectDelay:  2 * time.Second,
			AlwaysReconnect: true,
			UseHTTP2:        endpoints[0].UseHTTP2,
			OnConnected: func(endpoint net.Addr) {
				mu.Lock()
				if session == current && current.active {
					state, lastError = "connected", ""
				}
				mu.Unlock()
			},
			OnConnectError: func(endpoint net.Addr, connectErr error) {
				mu.Lock()
				if session == current && current.active {
					state, lastError = "retrying", connectErr.Error()
				}
				mu.Unlock()
			},
			OnDisconnected: func(endpoint net.Addr, disconnectErr error) {
				mu.Lock()
				if session == current && current.active {
					state, lastError = "retrying", disconnectErr.Error()
				}
				mu.Unlock()
			},
		})
		mu.Lock()
		if session == current && current.active {
			current.active = false
			state = "disconnected"
		}
		mu.Unlock()
	}()
	return nil
}

func parseEndpoints(value string) ([]api.TunnelEndpoint, error) {
	parts := strings.Split(value, ";")
	endpoints := make([]api.TunnelEndpoint, 0, len(parts))
	seen := make(map[string]bool)
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		scheme, address, ok := strings.Cut(part, "://")
		if !ok {
			return nil, fmt.Errorf("MASQUE endpoint scheme is missing: %q", part)
		}
		host, portText, err := net.SplitHostPort(address)
		if err != nil {
			return nil, fmt.Errorf("invalid MASQUE endpoint %q: %w", part, err)
		}
		ip := net.ParseIP(strings.Trim(host, "[]"))
		if ip == nil {
			return nil, fmt.Errorf("MASQUE endpoint must be a numeric IP: %q", host)
		}
		port, err := strconv.Atoi(portText)
		if err != nil || port < 1 || port > 65535 {
			return nil, fmt.Errorf("invalid MASQUE endpoint port: %q", portText)
		}
		var addr net.Addr
		useHTTP2 := false
		switch strings.ToLower(scheme) {
		case "udp":
			addr = &net.UDPAddr{IP: ip, Port: port}
		case "tcp":
			addr = &net.TCPAddr{IP: ip, Port: port}
			useHTTP2 = true
		default:
			return nil, fmt.Errorf("unsupported MASQUE endpoint scheme: %q", scheme)
		}
		key := strings.ToLower(scheme) + "://" + net.JoinHostPort(ip.String(), strconv.Itoa(port))
		if seen[key] {
			continue
		}
		seen[key] = true
		endpoints = append(endpoints, api.TunnelEndpoint{Address: addr, UseHTTP2: useHTTP2})
	}
	if len(endpoints) == 0 {
		return nil, errors.New("Cloudflare supplied no MASQUE endpoints")
	}
	if len(endpoints) > 16 {
		endpoints = endpoints[:16]
	}
	return endpoints, nil
}

// StopTunnel cancels the MASQUE tunnel and closes its detached Android TUN fd.
func StopTunnel() {
	mu.Lock()
	current := session
	if current == nil {
		state = "disconnected"
		mu.Unlock()
		return
	}
	current.active = false
	state = "stopping"
	current.cancel()
	_ = current.device.file.Close()
	done := current.done
	mu.Unlock()

	select {
	case <-done:
	case <-time.After(4 * time.Second):
	}

	mu.Lock()
	if session == current {
		session = nil
	}
	state, lastError = "disconnected", ""
	mu.Unlock()
}

func State() string {
	mu.Lock()
	defer mu.Unlock()
	return state
}

func LastError() string {
	mu.Lock()
	defer mu.Unlock()
	return lastError
}
