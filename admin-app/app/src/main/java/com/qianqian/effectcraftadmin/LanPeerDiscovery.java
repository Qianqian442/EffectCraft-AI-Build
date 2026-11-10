package com.qianqian.effectcraftadmin;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.net.wifi.WifiManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Discovers EffectCraft account nodes on the same Wi-Fi using Android NSD/mDNS.
 *
 * This is discovery only: it does not copy account records or trust a peer.
 * Cross-network connectivity and signed replication are deliberately separate
 * protocol phases and must not be inferred from a successful mDNS discovery.
 */
final class LanPeerDiscovery {
    static final String PREFS = "effectcraft_p2p";
    static final String KEY_NODE_ID = "node_id";
    static final String KEY_PEERS = "peer_snapshot";
    static final String SERVICE_TYPE = "_effectcraft-account._tcp.";
    static final int PORT = 8787;

    private final Context context;
    private final NsdManager nsd;
    private final String nodeId;
    private final Map<String, JSONObject> peers = new LinkedHashMap<>();
    private WifiManager.MulticastLock multicastLock;
    private NsdManager.RegistrationListener registrationListener;
    private NsdManager.DiscoveryListener discoveryListener;
    private boolean started;

    LanPeerDiscovery(Context context) {
        this.context = context.getApplicationContext();
        this.nsd = (NsdManager) this.context.getSystemService(Context.NSD_SERVICE);
        String saved = this.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_NODE_ID, "");
        if (saved == null || saved.length() < 16) {
            saved = UUID.randomUUID().toString();
            this.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit().putString(KEY_NODE_ID, saved).apply();
        }
        this.nodeId = saved;
    }

    static String getNodeId(Context context) {
        String saved = context.getApplicationContext()
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_NODE_ID, "");
        if (saved == null || saved.isEmpty()) {
            LanPeerDiscovery discovery = new LanPeerDiscovery(context);
            return discovery.nodeId;
        }
        return saved;
    }

    static JSONArray getSavedPeers(Context context) {
        String saved = context.getApplicationContext()
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_PEERS, "[]");
        try { return new JSONArray(saved); }
        catch (Exception ignored) { return new JSONArray(); }
    }

    synchronized void start() {
        if (started || nsd == null) return;
        started = true;
        acquireMulticastLock();
        registerLocalNode();
        discoverNodes();
    }

    synchronized void stop() {
        started = false;
        if (nsd != null && discoveryListener != null) {
            try { nsd.stopServiceDiscovery(discoveryListener); } catch (Exception ignored) { }
        }
        if (nsd != null && registrationListener != null) {
            try { nsd.unregisterService(registrationListener); } catch (Exception ignored) { }
        }
        discoveryListener = null;
        registrationListener = null;
        if (multicastLock != null && multicastLock.isHeld()) {
            try { multicastLock.release(); } catch (Exception ignored) { }
        }
        multicastLock = null;
    }

    private void acquireMulticastLock() {
        try {
            WifiManager wifi = (WifiManager) context.getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);
            if (wifi == null) return;
            multicastLock = wifi.createMulticastLock("EffectCraft-P2P-Discovery");
            multicastLock.setReferenceCounted(false);
            multicastLock.acquire();
        } catch (SecurityException ignored) {
            multicastLock = null;
        }
    }

    private void registerLocalNode() {
        NsdServiceInfo local = new NsdServiceInfo();
        local.setServiceName("EffectCraft-" + nodeId.substring(0, 8));
        local.setServiceType(SERVICE_TYPE);
        local.setPort(PORT);
        try {
            local.setAttribute("node", nodeId);
            local.setAttribute("protocol", "1");
        } catch (IllegalArgumentException ignored) { }

        registrationListener = new NsdManager.RegistrationListener() {
            @Override public void onServiceRegistered(NsdServiceInfo serviceInfo) { }
            @Override public void onRegistrationFailed(NsdServiceInfo serviceInfo, int errorCode) { }
            @Override public void onServiceUnregistered(NsdServiceInfo serviceInfo) { }
            @Override public void onUnregistrationFailed(NsdServiceInfo serviceInfo, int errorCode) { }
        };
        try { nsd.registerService(local, NsdManager.PROTOCOL_DNS_SD, registrationListener); }
        catch (Exception ignored) { }
    }

    private void discoverNodes() {
        discoveryListener = new NsdManager.DiscoveryListener() {
            @Override public void onDiscoveryStarted(String serviceType) { }
            @Override public void onStartDiscoveryFailed(String serviceType, int errorCode) {
                try { nsd.stopServiceDiscovery(this); } catch (Exception ignored) { }
            }
            @Override public void onStopDiscoveryFailed(String serviceType, int errorCode) { }
            @Override public void onDiscoveryStopped(String serviceType) { }
            @Override public void onServiceFound(NsdServiceInfo serviceInfo) {
                if (!SERVICE_TYPE.equals(serviceInfo.getServiceType())) return;
                try {
                    nsd.resolveService(serviceInfo, new NsdManager.ResolveListener() {
                        @Override public void onResolveFailed(NsdServiceInfo info, int errorCode) { }
                        @Override public void onServiceResolved(NsdServiceInfo info) {
                            rememberPeer(info);
                        }
                    });
                } catch (Exception ignored) { }
            }
            @Override public void onServiceLost(NsdServiceInfo serviceInfo) {
                synchronized (LanPeerDiscovery.this) {
                    String name = serviceInfo.getServiceName();
                    peers.values().removeIf(peer -> name.equals(peer.optString("service")));
                    saveSnapshot();
                }
            }
        };
        try { nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discoveryListener); }
        catch (Exception ignored) { }
    }

    private synchronized void rememberPeer(NsdServiceInfo info) {
        InetAddress host = info.getHost();
        if (!(host instanceof Inet4Address) || !host.isSiteLocalAddress()) return;
        String remoteIp = host.getHostAddress();
        if (remoteIp == null || remoteIp.isEmpty() || info.getPort() <= 0) return;

        String remoteNode = info.getAttributes() == null ? null :
            decode(info.getAttributes().get("node"));
        if (remoteNode == null || remoteNode.isEmpty()) remoteNode = info.getServiceName();
        if (nodeId.equals(remoteNode)) return;

        JSONObject peer = new JSONObject();
        try {
            peer.put("node_id", remoteNode);
            peer.put("service", info.getServiceName());
            peer.put("address", remoteIp);
            peer.put("port", info.getPort());
            peer.put("protocol", decode(info.getAttributes() == null ? null : info.getAttributes().get("protocol")));
            peer.put("last_seen_ms", System.currentTimeMillis());
            peers.put(remoteNode, peer);
            saveSnapshot();
        } catch (Exception ignored) { }
    }

    private static String decode(byte[] bytes) {
        return bytes == null ? "" : new String(bytes, StandardCharsets.UTF_8);
    }

    private void saveSnapshot() {
        JSONArray array = new JSONArray();
        for (JSONObject peer : peers.values()) array.put(peer);
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_PEERS, array.toString()).apply();
    }
}
