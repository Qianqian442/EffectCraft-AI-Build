package warpandroid

import (
	"net"
	"testing"
)

func isolateScannerState(t *testing.T) {
	t.Helper()
	scannerMu.Lock()
	oldPath, oldKey, oldBook := scannerPath, scannerNetworkKey, scannerBook
	scannerPath = ""
	scannerNetworkKey = "unit-test-network"
	scannerBook = nil
	scannerMu.Unlock()
	t.Cleanup(func() {
		scannerMu.Lock()
		scannerPath, scannerNetworkKey, scannerBook = oldPath, oldKey, oldBook
		scannerMu.Unlock()
	})
}

func TestMakeH2CandidatesPrioritizesKnownFastEndpoints(t *testing.T) {
	defaultEndpoint := &net.TCPAddr{IP: net.ParseIP("162.159.198.2").To4(), Port: 443}
	snapshot := map[string]endpointScanRecord{
		"162.159.198.9:8443": {Score: 5, RTTMillis: 80},
		"162.159.198.8:443":  {Score: 3, RTTMillis: 140},
		"162.159.198.7:1701": {Score: 1, RTTMillis: 250},
	}
	got := makeH2Candidates(defaultEndpoint, snapshot)
	if len(got) < 4 {
		t.Fatalf("expected three cached endpoints plus default, got %d", len(got))
	}
	want := []string{"162.159.198.9:8443", "162.159.198.8:443", "162.159.198.7:1701", "162.159.198.2:443"}
	for i, expected := range want {
		if got[i].String() != expected {
			t.Fatalf("candidate %d = %s, want %s", i, got[i], expected)
		}
	}
}

func TestMakeH2CandidatesOnlyReturnsCloudflareH2RangeAndPorts(t *testing.T) {
	defaultEndpoint := &net.TCPAddr{IP: net.ParseIP("1.1.1.1").To4(), Port: 443}
	snapshot := map[string]endpointScanRecord{
		"1.1.1.1:443":         {Score: 9, RTTMillis: 1},
		"162.159.198.10:8443": {Score: 8, RTTMillis: 2},
		"162.159.199.2:443":   {Score: 7, RTTMillis: 3},
		"162.159.198.11:443":  {Score: 4, RTTMillis: 100},
		"162.159.198.12:80":   {Score: 10, RTTMillis: 1},
		"162.159.198.1:443":   {Score: 10, RTTMillis: 1},
	}
	got := makeH2Candidates(defaultEndpoint, snapshot)
	if len(got) == 0 {
		t.Fatal("expected at least one Cloudflare H2 candidate")
	}
	for _, endpoint := range got {
		if !isCloudflareH2Endpoint(endpoint) {
			t.Fatalf("scanner returned an unapproved endpoint: %s", endpoint)
		}
	}
	if got[0].String() != "162.159.198.10:8443" {
		t.Fatalf("first endpoint = %s, want highest-scored valid endpoint 162.159.198.10:8443", got[0])
	}
}

func TestMakeH2CandidatesIncludesAlternativeTCPPorts(t *testing.T) {
	defaultEndpoint := &net.TCPAddr{IP: net.ParseIP("162.159.198.2").To4(), Port: 443}
	got := makeH2Candidates(defaultEndpoint, nil)
	seen := map[int]bool{}
	for _, endpoint := range got {
		if endpoint.IP.Equal(defaultEndpoint.IP) {
			seen[endpoint.Port] = true
		}
	}
	for _, port := range []int{443, 500, 1701, 4500, 4443, 8443, 8095} {
		if !seen[port] {
			t.Fatalf("candidate list did not include Cloudflare TCP fallback port %d on the default H2 address", port)
		}
	}
}

func TestEndpointScoreRecordsOnlyCloudflareTCPH2Endpoints(t *testing.T) {
	isolateScannerState(t)
	udp := &net.UDPAddr{IP: net.ParseIP("162.159.198.2").To4(), Port: 443}
	wrongIP := &net.TCPAddr{IP: net.ParseIP("1.1.1.1").To4(), Port: 443}
	wrongPort := &net.TCPAddr{IP: net.ParseIP("162.159.198.2").To4(), Port: 80}
	wrongRange := &net.TCPAddr{IP: net.ParseIP("162.159.199.2").To4(), Port: 443}
	recordEndpointScanSuccess(udp, 100000000)
	recordEndpointScanSuccess(wrongIP, 100000000)
	recordEndpointScanSuccess(wrongPort, 100000000)
	recordEndpointScanSuccess(wrongRange, 100000000)
	if snapshot := endpointRecordSnapshot(); len(snapshot) != 0 {
		t.Fatalf("invalid endpoint types, ports or ranges were recorded: %#v", snapshot)
	}

	valid := &net.TCPAddr{IP: net.ParseIP("162.159.198.2").To4(), Port: 8443}
	recordEndpointScanSuccess(valid, 100000000)
	snapshot := endpointRecordSnapshot()
	if snapshot[valid.String()].Score != 1 {
		t.Fatalf("valid H2 endpoint score = %d, want 1", snapshot[valid.String()].Score)
	}
	recordEndpointScanFailure(valid)
	snapshot = endpointRecordSnapshot()
	if snapshot[valid.String()].Score != 0 {
		t.Fatalf("failed H2 endpoint score = %d, want 0", snapshot[valid.String()].Score)
	}
}

func TestScannerNetworkIdentityIsHashedAndSeparated(t *testing.T) {
	isolateScannerState(t)
	SetScannerStorage("", "wifi|dns=192.0.2.1|subnet=192.0.2.10/24")
	wifiKey := scannerNetworkKey
	if wifiKey == "" || wifiKey == "wifi|dns=192.0.2.1|subnet=192.0.2.10/24" {
		t.Fatalf("network identity was not hashed: %q", wifiKey)
	}
	SetScannerStorage("", "cellular|dns=192.0.2.2|subnet=198.51.100.10/24")
	cellKey := scannerNetworkKey
	if cellKey == wifiKey {
		t.Fatal("Wi-Fi and cellular network identities unexpectedly share a score bucket")
	}
	SetScannerStorage("", "wifi|dns=192.0.2.1|subnet=192.0.2.10/24")
	if scannerNetworkKey != wifiKey {
		t.Fatal("same network identity did not produce a stable score bucket")
	}
}
