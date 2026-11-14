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
		"162.159.198.9:443": {Score: 5, RTTMillis: 80},
		"162.159.198.8:443": {Score: 3, RTTMillis: 140},
		"162.159.198.7:443": {Score: 1, RTTMillis: 250},
	}
	got := makeH2Candidates(defaultEndpoint, snapshot)
	if len(got) < 4 {
		t.Fatalf("expected three cached endpoints plus default, got %d", len(got))
	}
	if got[0].IP.String() != "162.159.198.9" {
		t.Fatalf("first endpoint = %s, want highest-scored endpoint 162.159.198.9", got[0])
	}
	if got[1].IP.String() != "162.159.198.8" {
		t.Fatalf("second endpoint = %s, want 162.159.198.8", got[1])
	}
	if got[2].IP.String() != "162.159.198.7" {
		t.Fatalf("third endpoint = %s, want third cached endpoint 162.159.198.7", got[2])
	}
	if got[3].IP.String() != "162.159.198.2" {
		t.Fatalf("fourth endpoint = %s, want configured default 162.159.198.2", got[3])
	}
}

func TestMakeH2CandidatesOnlyReturnsCloudflareH2Range(t *testing.T) {
	defaultEndpoint := &net.TCPAddr{IP: net.ParseIP("1.1.1.1").To4(), Port: 443}
	snapshot := map[string]endpointScanRecord{
		"1.1.1.1:443":             {Score: 9, RTTMillis: 1},
		"162.159.198.10:8443":     {Score: 8, RTTMillis: 2},
		"162.159.199.2:443":       {Score: 7, RTTMillis: 3},
		"162.159.198.11:443":      {Score: 4, RTTMillis: 100},
	}
	got := makeH2Candidates(defaultEndpoint, snapshot)
	if len(got) == 0 {
		t.Fatal("expected at least one Cloudflare H2 candidate")
	}
	for _, endpoint := range got {
		ip := endpoint.IP.To4()
		if ip == nil || ip[0] != 162 || ip[1] != 159 || ip[2] != 198 || endpoint.Port != 443 {
			t.Fatalf("scanner returned an unapproved endpoint: %s", endpoint)
		}
	}
	if got[0].IP.String() != "162.159.198.11" {
		t.Fatalf("first endpoint = %s, want valid cached Cloudflare address", got[0])
	}
}

func TestEndpointScoreRecordsOnlyCloudflareTCP443(t *testing.T) {
	isolateScannerState(t)
	udp := &net.UDPAddr{IP: net.ParseIP("162.159.198.2").To4(), Port: 443}
	wrongIP := &net.TCPAddr{IP: net.ParseIP("1.1.1.1").To4(), Port: 443}
	wrongPort := &net.TCPAddr{IP: net.ParseIP("162.159.198.2").To4(), Port: 8443}
	recordEndpointScanSuccess(udp, 100000000)
	recordEndpointScanSuccess(wrongIP, 100000000)
	recordEndpointScanSuccess(wrongPort, 100000000)
	if snapshot := endpointRecordSnapshot(); len(snapshot) != 0 {
		t.Fatalf("invalid endpoint types or ranges were recorded: %#v", snapshot)
	}

	valid := &net.TCPAddr{IP: net.ParseIP("162.159.198.2").To4(), Port: 443}
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
