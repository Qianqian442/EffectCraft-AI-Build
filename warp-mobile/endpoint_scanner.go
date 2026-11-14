package warpandroid

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/rand"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	cloudflareH2RangePrefix = "162.159.198."
	scannerMaxCandidates   = 32
	scannerMaxWorkers      = 8
	scannerMaxResults      = 4
	scannerProbeTimeout    = 3500 * time.Millisecond
	scannerMaxRTT          = 3200 * time.Millisecond
	scannerStableScore     = 3
	scannerRecordLifetime  = 30 * 24 * time.Hour
	scannerPenaltyPeriod   = 2 * time.Minute
)

// Cloudflare consumer WARP MASQUE accepts HTTP/2 over these TCP ports.
// Trying only 443 silently leaves TCP-blocked networks with QUIC/UDP as
// the only working path, which is frequently unavailable on restrictive mobile networks.
var cloudflareH2Ports = []int{443, 500, 1701, 4500, 4443, 8443, 8095}

func isCloudflareH2Endpoint(endpoint *net.TCPAddr) bool {
	if endpoint == nil || endpoint.IP == nil || endpoint.IP.To4() == nil {
		return false
	}
	ip := endpoint.IP.To4()
	if ip[0] != 162 || ip[1] != 159 || ip[2] != 198 || ip[3] < 2 {
		return false
	}
	for _, port := range cloudflareH2Ports {
		if endpoint.Port == port {
			return true
		}
	}
	return false
}

type endpointScanRecord struct {
	Score       int   `json:"score"`
	RTTMillis   int64 `json:"rtt_ms,omitempty"`
	LastSuccess int64 `json:"last_success,omitempty"`
	LastPenalty int64 `json:"last_penalty,omitempty"`
}

type endpointScanBook struct {
	Networks map[string]map[string]*endpointScanRecord `json:"networks"`
}

var (
	scannerMu          sync.Mutex
	scannerPath        string
	scannerNetworkKey  = "default"
	scannerBook        *endpointScanBook
)

// SetScannerStorage configures a private app-storage file and a non-sensitive
// network fingerprint. The fingerprint is hashed before it is persisted.
func SetScannerStorage(path string, networkIdentity string) {
	scannerMu.Lock()
	defer scannerMu.Unlock()

	if strings.TrimSpace(path) != "" {
		scannerPath = filepath.Clean(path)
	}
	identity := strings.TrimSpace(networkIdentity)
	if identity == "" {
		identity = "android-default"
	}
	sum := sha256.Sum256([]byte(identity))
	scannerNetworkKey = hex.EncodeToString(sum[:12])
	scannerBook = nil
}

func loadEndpointScanBookLocked() *endpointScanBook {
	if scannerBook != nil {
		return scannerBook
	}
	book := &endpointScanBook{Networks: make(map[string]map[string]*endpointScanRecord)}
	if scannerPath != "" {
		if content, err := os.ReadFile(scannerPath); err == nil && len(content) <= 512*1024 {
			var saved endpointScanBook
			if json.Unmarshal(content, &saved) == nil && saved.Networks != nil {
				book = &saved
			}
		}
	}
	scannerBook = book
	return book
}

func saveEndpointScanBookLocked(book *endpointScanBook) {
	if scannerPath == "" || book == nil {
		return
	}
	now := time.Now()
	for network, records := range book.Networks {
		for endpoint, record := range records {
			if record == nil || record.LastSuccess == 0 || now.Sub(time.Unix(record.LastSuccess, 0)) > scannerRecordLifetime {
				delete(records, endpoint)
			}
		}
		if len(records) == 0 {
			delete(book.Networks, network)
		}
	}
	content, err := json.Marshal(book)
	if err != nil {
		return
	}
	dir := filepath.Dir(scannerPath)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return
	}
	temp := scannerPath + ".tmp"
	if err := os.WriteFile(temp, content, 0600); err != nil {
		return
	}
	if err := os.Rename(temp, scannerPath); err != nil {
		_ = os.Remove(temp)
	}
}

func endpointRecordSnapshot() map[string]endpointScanRecord {
	scannerMu.Lock()
	defer scannerMu.Unlock()
	book := loadEndpointScanBookLocked()
	records := book.Networks[scannerNetworkKey]
	snapshot := make(map[string]endpointScanRecord, len(records))
	for address, record := range records {
		if record != nil {
			snapshot[address] = *record
		}
	}
	return snapshot
}

func recordEndpointScanSuccess(endpoint net.Addr, rtt time.Duration) {
	tcp, ok := endpoint.(*net.TCPAddr)
	if !ok || !isCloudflareH2Endpoint(tcp) {
		return
	}
	scannerMu.Lock()
	defer scannerMu.Unlock()
	book := loadEndpointScanBookLocked()
	records := book.Networks[scannerNetworkKey]
	if records == nil {
		records = make(map[string]*endpointScanRecord)
		book.Networks[scannerNetworkKey] = records
	}
	key := endpoint.String()
	record := records[key]
	if record == nil {
		record = &endpointScanRecord{}
		records[key] = record
	}
	if record.Score < 0 {
		record.Score = 1
	} else if record.Score < 5 {
		record.Score++
	}
	if rtt > 0 {
		record.RTTMillis = rtt.Milliseconds()
	}
	record.LastSuccess = time.Now().Unix()
	saveEndpointScanBookLocked(book)
}

func recordEndpointScanFailure(endpoint net.Addr) {
	tcp, ok := endpoint.(*net.TCPAddr)
	if !ok || !isCloudflareH2Endpoint(tcp) {
		return
	}
	scannerMu.Lock()
	defer scannerMu.Unlock()
	book := loadEndpointScanBookLocked()
	records := book.Networks[scannerNetworkKey]
	if records == nil {
		records = make(map[string]*endpointScanRecord)
		book.Networks[scannerNetworkKey] = records
	}
	key := endpoint.String()
	record := records[key]
	if record == nil {
		record = &endpointScanRecord{}
		records[key] = record
	}
	now := time.Now()
	if record.LastPenalty != 0 && now.Sub(time.Unix(record.LastPenalty, 0)) < scannerPenaltyPeriod {
		return
	}
	if record.Score > -5 {
		record.Score--
	}
	record.LastPenalty = now.Unix()
	saveEndpointScanBookLocked(book)
}

type scoredH2Endpoint struct {
	address *net.TCPAddr
	score   int
	rtt     time.Duration
}

// scanCloudflareHTTP2 probes Cloudflare's documented consumer MASQUE HTTP/2
// range directly over TCP/443. It only accepts the TLS key pinned by the
// device's Cloudflare enrollment response. UDP/QUIC candidates remain a
// separate fallback and are appended by the caller.
func scanCloudflareHTTP2(ctx context.Context, baseTLS *tls.Config, defaultEndpoint *net.TCPAddr) []net.Addr {
	if baseTLS == nil {
		if defaultEndpoint != nil {
			return []net.Addr{defaultEndpoint}
		}
		return nil
	}

	snapshot := endpointRecordSnapshot()
	candidates := makeH2Candidates(defaultEndpoint, snapshot)
	if len(candidates) == 0 {
		return nil
	}

	scanCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	jobs := make(chan *net.TCPAddr)
	var workers sync.WaitGroup
	var resultsMu sync.Mutex
	results := make([]scoredH2Endpoint, 0, scannerMaxResults)
	workerCount := min(scannerMaxWorkers, len(candidates))

	for range workerCount {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for endpoint := range jobs {
				probeCtx, probeCancel := context.WithTimeout(scanCtx, scannerProbeTimeout)
				rtt, err := probeCloudflareH2(probeCtx, endpoint, baseTLS)
				probeCancel()

				if err != nil || rtt > scannerMaxRTT {
					if scanCtx.Err() == nil {
						recordEndpointScanFailure(endpoint)
					}
					continue
				}

				// A TLS/ALPN probe is not proof that Cloudflare accepted CONNECT-IP.
				// Only OnConnected below awards a durable success score.
				score := endpointRecordSnapshot()[endpoint.String()].Score
				resultsMu.Lock()
				results = append(results, scoredH2Endpoint{address: endpoint, score: score, rtt: rtt})
				enough := len(results) >= scannerMaxResults || score >= scannerStableScore
				resultsMu.Unlock()
				if enough {
					cancel()
				}
			}
		}()
	}

feed:
	for _, endpoint := range candidates {
		select {
		case jobs <- endpoint:
		case <-scanCtx.Done():
			break feed
		}
	}
	close(jobs)
	workers.Wait()

	sort.Slice(results, func(i, j int) bool {
		if results[i].score != results[j].score {
			return results[i].score > results[j].score
		}
		return results[i].rtt < results[j].rtt
	})

	selected := make([]net.Addr, 0, len(results))
	for _, result := range results {
		selected = append(selected, result.address)
	}
	if len(selected) == 0 && defaultEndpoint != nil {
		// Keep a known Cloudflare endpoint as the final TCP attempt if probing
		// is blocked before a TLS result can be obtained.
		selected = append(selected, defaultEndpoint)
	}
	return selected
}

func makeH2Candidates(defaultEndpoint *net.TCPAddr, snapshot map[string]endpointScanRecord) []*net.TCPAddr {
	seen := make(map[string]bool)
	candidates := make([]*net.TCPAddr, 0, scannerMaxCandidates)

	add := func(address *net.TCPAddr) {
		if !isCloudflareH2Endpoint(address) {
			return
		}
		key := address.String()
		if seen[key] || len(candidates) >= scannerMaxCandidates {
			return
		}
		seen[key] = true
		candidates = append(candidates, &net.TCPAddr{
			IP: append(net.IP(nil), address.IP.To4()...),
			Port: address.Port,
		})
	}

	// Previously successful endpoint IP:port pairs are tried first by score,
	// followed by the configured Cloudflare default endpoint.
	type cached struct {
		endpoint *net.TCPAddr
		record endpointScanRecord
	}
	var known []cached
	for raw, record := range snapshot {
		host, portText, err := net.SplitHostPort(raw)
		if err != nil || record.Score <= 0 {
			continue
		}
		port, err := strconv.Atoi(portText)
		if err != nil {
			continue
		}
		ip := net.ParseIP(host)
		if ip == nil || ip.To4() == nil {
			continue
		}
		endpoint := &net.TCPAddr{IP: ip.To4(), Port: port}
		if !isCloudflareH2Endpoint(endpoint) {
			continue
		}
		known = append(known, cached{endpoint: endpoint, record: record})
	}
	sort.Slice(known, func(i, j int) bool {
		if known[i].record.Score != known[j].record.Score {
			return known[i].record.Score > known[j].record.Score
		}
		return known[i].record.RTTMillis < known[j].record.RTTMillis
	})
	for _, item := range known {
		add(item.endpoint)
	}

	add(defaultEndpoint)

	// Explicitly cover alternative Cloudflare TCP ports on common consumer
	// endpoints before random scanning, so a filtered TCP/443 does not force
	// the client to rely on UDP/QUIC alone.
	for _, lastOctet := range []byte{2, 10} {
		for _, port := range cloudflareH2Ports {
			add(&net.TCPAddr{IP: net.IPv4(162, 159, 198, lastOctet), Port: port})
		}
	}

	type target struct {
		host byte
		port int
	}
	targets := make([]target, 0, 253*len(cloudflareH2Ports))
	for host := 2; host <= 254; host++ {
		for _, port := range cloudflareH2Ports {
			targets = append(targets, target{host: byte(host), port: port})
		}
	}
	rng := rand.New(rand.NewSource(time.Now().UnixNano()))
	rng.Shuffle(len(targets), func(i, j int) {
		targets[i], targets[j] = targets[j], targets[i]
	})
	for _, item := range targets {
		add(&net.TCPAddr{
			IP: net.IPv4(162, 159, 198, item.host),
			Port: item.port,
		})
		if len(candidates) >= scannerMaxCandidates {
			break
		}
	}
	return candidates
}

func probeCloudflareH2(ctx context.Context, endpoint *net.TCPAddr, baseTLS *tls.Config) (time.Duration, error) {
	start := time.Now()
	dialer := &net.Dialer{Timeout: scannerProbeTimeout, KeepAlive: 15 * time.Second}
	conn, err := dialer.DialContext(ctx, "tcp", endpoint.String())
	if err != nil {
		return 0, fmt.Errorf("TCP/443 dial %s: %w", endpoint, err)
	}
	defer conn.Close()

	tlsConfig := baseTLS.Clone()
	tlsConfig.NextProtos = []string{"h2"}
	tlsConn := tls.Client(conn, tlsConfig)
	if err := tlsConn.HandshakeContext(ctx); err != nil {
		return 0, fmt.Errorf("Cloudflare MASQUE TLS handshake %s: %w", endpoint, err)
	}
	defer tlsConn.Close()

	if tlsConn.ConnectionState().NegotiatedProtocol != "h2" {
		return 0, fmt.Errorf("Cloudflare MASQUE endpoint %s did not negotiate HTTP/2", endpoint)
	}
	return time.Since(start), nil
}
