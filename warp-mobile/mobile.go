package warpandroid

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
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
	mu             sync.Mutex
	registrationMu sync.Mutex
	session        *tunnelSession
	state          = "disconnected"
	lastError      = ""
)

// configureDirectRegistrationClient forces Cloudflare device registration
// to use the phone's own network directly, never an environment HTTP proxy.
// Every network phase is bounded so a blocked Cloudflare API cannot hang login.
func configureDirectRegistrationClient() {
	// Cloudflare's registration/control-plane API must be reached before a WARP
	// tunnel exists. Use Cloudflare's published API IPs and hostname fallback
	// directly, with matching TLS SNI/Host and normal certificate verification.
	http.DefaultClient = &http.Client{
		Transport: newCloudflareAPIDirectTransport(),
		Timeout:   50 * time.Second,
	}
}

// RegisterDevice enrolls a unique MASQUE identity for this Android installation.
// The caller must obtain the user's explicit Cloudflare Terms consent before calling it.
// The returned JSON must be stored encrypted with Android Keystore protection.
func RegisterDevice() (string, error) {
	registrationMu.Lock()
	defer registrationMu.Unlock()
	configureDirectRegistrationClient()

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

	// Prefer Cloudflare's TCP/443 HTTP/2 MASQUE endpoint first for
	// networks where UDP/QUIC is filtered or rate-limited (including many
	// mainland mobile networks). UDP endpoints remain automatic fallbacks.
	h2IP := cfg.EndpointH2V4
	if net.ParseIP(h2IP) == nil {
		return "", errors.New("Cloudflare HTTP/2 fallback endpoint is invalid")
	}
	h2 := "tcp://" + net.JoinHostPort(h2IP, "443")
	endpointSet := []string{h2}
	seen := map[string]bool{h2: true}
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
		var defaultH2 *net.TCPAddr
		for _, candidate := range endpoints {
			if candidate.UseHTTP2 {
				if tcp, ok := candidate.Address.(*net.TCPAddr); ok {
					defaultH2 = tcp
					break
				}
			}
		}
		selectedH2 := scanCloudflareHTTP2(ctx, tlsConfig, defaultH2)
		selected := make([]api.TunnelEndpoint, 0, 6)
		for _, address := range selectedH2 {
			selected = append(selected, api.TunnelEndpoint{Address: address, UseHTTP2: true})
		}
		for _, candidate := range endpoints {
			if !candidate.UseHTTP2 && len(selected) < 6 {
				selected = append(selected, candidate)
			}
		}
		if len(selected) == 0 {
			selected = endpoints
		}
		if len(selected) > 6 {
			selected = selected[:6]
		}

		var diagnosticsMu sync.Mutex
		var recentFailures []string
		appendEndpointFailure := func(endpoint net.Addr, cause error) string {
			protocol := "HTTP/3 QUIC (UDP)"
			if _, ok := endpoint.(*net.TCPAddr); ok {
				protocol = "HTTP/2 (TCP)"
			}
			message := fmt.Sprintf("%s endpoint %s: %v", protocol, endpoint.String(), cause)
			diagnosticsMu.Lock()
			recentFailures = append(recentFailures, message)
			if len(recentFailures) > 4 {
				recentFailures = append([]string(nil), recentFailures[len(recentFailures)-4:]...)
			}
			combined := strings.Join(recentFailures, " | ")
			diagnosticsMu.Unlock()
			return combined
		}

		api.MaintainTunnel(ctx, api.MaintainTunnelConfig{
			TLSConfig:       tlsConfig,
			KeepalivePeriod: 20 * time.Second,
			Endpoint:        selected[0].Address,
			Endpoints:       selected,
			Device:          device,
			MTU:             1280,
			ReconnectDelay:  2 * time.Second,
			AlwaysReconnect: true,
			UseHTTP2:        selected[0].UseHTTP2,
			OnConnected: func(endpoint net.Addr) {
				diagnosticsMu.Lock()
				recentFailures = nil
				diagnosticsMu.Unlock()
				mu.Lock()
				if session == current && current.active {
					state, lastError = "connected", ""
					recordEndpointScanSuccess(endpoint, 0)
				}
				mu.Unlock()
			},
			OnConnectError: func(endpoint net.Addr, connectErr error) {
				detail := appendEndpointFailure(endpoint, connectErr)
				mu.Lock()
				if session == current && current.active {
					state, lastError = "retrying", detail
					recordEndpointScanFailure(endpoint)
				}
				mu.Unlock()
			},
			OnDisconnected: func(endpoint net.Addr, disconnectErr error) {
				if disconnectErr == nil { disconnectErr = errors.New("MASQUE stream closed") }
				detail := appendEndpointFailure(endpoint, disconnectErr)
				mu.Lock()
				if session == current && current.active {
					state, lastError = "retrying", detail
					recordEndpointScanFailure(endpoint)
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
