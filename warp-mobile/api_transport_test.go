package warpandroid

import "testing"

func TestCloudflareAPIEndpointPoolStartsWithPublishedDirectEndpoints(t *testing.T) {
	if len(cloudflareAPIEndpointPool) < 6 {
		t.Fatalf("API endpoint pool has %d entries, want at least 6", len(cloudflareAPIEndpointPool))
	}
	want := []warpAPIEndpoint{
		{Host: "api.devices.cloudflare.com", IP: "162.159.137.105"},
		{Host: "api.devices.cloudflare.com", IP: "162.159.138.105"},
	}
	for i, expected := range want {
		if cloudflareAPIEndpointPool[i] != expected {
			t.Fatalf("API endpoint %d = %#v, want %#v", i, cloudflareAPIEndpointPool[i], expected)
		}
	}
	for _, endpoint := range cloudflareAPIEndpointPool {
		if endpoint.Host != "api.devices.cloudflare.com" &&
			endpoint.Host != "api.cloudflareclient.com" {
			t.Fatalf("unexpected Cloudflare API host: %s", endpoint.Host)
		}
		if endpoint.IP == "" {
			t.Fatal("Cloudflare API endpoint must use a pinned numeric IP")
		}
	}
}

func TestCloudflareAPIPreferredHostIsTriedFirst(t *testing.T) {
	transport := newCloudflareAPIDirectTransport()
	transport.preferredHost = "api.cloudflareclient.com"
	endpoints := transport.orderedEndpoints()
	if len(endpoints) == 0 || endpoints[0].Host != "api.cloudflareclient.com" {
		t.Fatalf("preferred API host was not moved to the front: %#v", endpoints)
	}
}
