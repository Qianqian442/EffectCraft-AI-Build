package warpandroid

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptrace"
	"sync"
	"sync/atomic"
	"time"
)

// These API endpoints are Cloudflare-owned control-plane addresses. The first
// two are published by Cloudflare for its device orchestration API. The legacy
// consumer API and edge addresses are a direct-connect fallback, not proxies.
type warpAPIEndpoint struct {
	Host string
	IP   string
}

var cloudflareAPIEndpointPool = []warpAPIEndpoint{
	{Host: "api.devices.cloudflare.com", IP: "162.159.137.105"},
	{Host: "api.devices.cloudflare.com", IP: "162.159.138.105"},
	{Host: "api.cloudflareclient.com", IP: "104.16.80.230"},
	{Host: "api.cloudflareclient.com", IP: "104.17.143.163"},
	{Host: "api.devices.cloudflare.com", IP: "104.24.4.6"},
	{Host: "api.devices.cloudflare.com", IP: "104.18.0.6"},
}

type cloudflareAPIDirectTransport struct {
	mu           sync.Mutex
	preferredHost string
}

type cancelOnCloseBody struct {
	io.ReadCloser
	cancel context.CancelFunc
}

func (b *cancelOnCloseBody) Close() error {
	err := b.ReadCloser.Close()
	b.cancel()
	return err
}

func newCloudflareAPIDirectTransport() *cloudflareAPIDirectTransport {
	return &cloudflareAPIDirectTransport{}
}

func (t *cloudflareAPIDirectTransport) orderedEndpoints() []warpAPIEndpoint {
	t.mu.Lock()
	preferred := t.preferredHost
	t.mu.Unlock()

	out := make([]warpAPIEndpoint, 0, len(cloudflareAPIEndpointPool))
	if preferred != "" {
		for _, endpoint := range cloudflareAPIEndpointPool {
			if endpoint.Host == preferred {
				out = append(out, endpoint)
			}
		}
	}
	for _, endpoint := range cloudflareAPIEndpointPool {
		if endpoint.Host != preferred || preferred == "" {
			out = append(out, endpoint)
		}
	}
	return out
}

// RoundTrip pins the TCP dial to known Cloudflare API IPs while preserving the
// matching HTTPS hostname for SNI, :authority/Host and certificate validation.
// It never uses an HTTP proxy, DNS-based endpoint substitution, or an admin relay.
// Mutating requests are never replayed after their bytes have been written.
func (t *cloudflareAPIDirectTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if req == nil || req.URL == nil || req.URL.Scheme != "https" {
		return nil, errors.New("Cloudflare API transport only accepts HTTPS requests")
	}
	if req.URL.Hostname() != "api.cloudflareclient.com" &&
		req.URL.Hostname() != "api.devices.cloudflare.com" {
		return nil, fmt.Errorf("Cloudflare API host is not allowed: %q", req.URL.Hostname())
	}

	var lastErr error
	for _, endpoint := range t.orderedEndpoints() {
		var wroteRequest atomic.Bool
		trace := &httptrace.ClientTrace{
			WroteRequest: func(httptrace.WroteRequestInfo) {
				wroteRequest.Store(true)
			},
		}
		attemptCtx, cancel := context.WithTimeout(
			httptrace.WithClientTrace(req.Context(), trace),
			8*time.Second,
		)

		attempt := req.Clone(attemptCtx)
		urlCopy := *req.URL
		urlCopy.Scheme = "https"
		urlCopy.Host = endpoint.Host
		attempt.URL = &urlCopy
		attempt.Host = endpoint.Host

		if req.Body != nil {
			if req.GetBody == nil {
				cancel()
				return nil, errors.New("Cloudflare API request body cannot be safely replayed")
			}
			body, err := req.GetBody()
			if err != nil {
				cancel()
				return nil, fmt.Errorf("recreate Cloudflare API request body: %w", err)
			}
			attempt.Body = body
		}

		dialer := &net.Dialer{
			Timeout:   5 * time.Second,
			KeepAlive: 15 * time.Second,
		}
		transport := &http.Transport{
			Proxy:                 nil,
			ForceAttemptHTTP2:     true,
			DisableKeepAlives:     true,
			TLSHandshakeTimeout:   5 * time.Second,
			ResponseHeaderTimeout: 6 * time.Second,
			TLSClientConfig: &tls.Config{
				ServerName: endpoint.Host,
				MinVersion: tls.VersionTLS12,
			},
			DialContext: func(ctx context.Context, network, _ string) (net.Conn, error) {
				return dialer.DialContext(ctx, "tcp", net.JoinHostPort(endpoint.IP, "443"))
			},
		}

		response, err := transport.RoundTrip(attempt)
		if err == nil {
			t.mu.Lock()
			t.preferredHost = endpoint.Host
			t.mu.Unlock()
			if response.Body != nil {
				response.Body = &cancelOnCloseBody{ReadCloser: response.Body, cancel: cancel}
			} else {
				cancel()
			}
			return response, nil
		}

		transport.CloseIdleConnections()
		cancel()
		lastErr = fmt.Errorf("%s (%s): %w", endpoint.Host, endpoint.IP, err)

		// Register and MASQUE-enrollment calls change server state. If bytes
		// reached the API but its response was lost, replaying could create
		// duplicate device registrations or duplicate key operations.
		if wroteRequest.Load() && req.Method != http.MethodGet && req.Method != http.MethodHead {
			return nil, fmt.Errorf(
				"Cloudflare API request was sent to %s (%s), but no response arrived; not replayed to avoid duplicate registration: %w",
				endpoint.Host, endpoint.IP, err,
			)
		}
	}
	if lastErr == nil {
		lastErr = errors.New("no Cloudflare API endpoints were available")
	}
	return nil, fmt.Errorf("all direct Cloudflare API endpoints failed: %w", lastErr)
}
