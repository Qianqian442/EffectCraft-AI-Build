package com.qianqian.effectcraftadmin;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.Socket;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import javax.net.ssl.HttpsURLConnection;
import java.util.Map;

/**
 * End-to-end TLS transport for the Cloudflare account API.
 *
 * Public proxies are untrusted byte tunnels only. HTTPS certificate and hostname
 * verification are left at Android's defaults. The proxy can see the destination
 * host, connection timing and data volume, but TLS protects request bodies/tokens.
 * Never add a custom TrustManager or permissive HostnameVerifier here.
 */
final class CloudflareProxyPool {
    private CloudflareProxyPool() {}

    private static final Object LOCK = new Object();
    private static final long FEED_REFRESH_MS = 30L * 60L * 1000L;
    private static final long BAD_COOLDOWN_MS = 15L * 60L * 1000L;
    private static final long GOOD_TTL_MS = 2L * 60L * 1000L;
    private static final long DIRECT_TTL_MS = 60L * 1000L;
    private static final int MAX_CANDIDATES = 600;
    private static final int MAX_PER_FEED = 80;
    private static final int MAX_TRIES = 18;
    private static final int CONNECT_TIMEOUT_MS = 2200;
    private static final int READ_TIMEOUT_MS = 3500;

    private static final class Feed {
        final String url;
        final String defaultProtocol;
        Feed(String url, String defaultProtocol) {
            this.url = url;
            this.defaultProtocol = defaultProtocol;
        }
    }

    private static final Feed[] FEEDS = new Feed[] {
        // Mainland China-only proxy candidates. No HK, JP, SG or global fallback feeds.
        new Feed("https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/cn.txt", "http"),
        // Independent mainland-China-only source; protocol is defined by each file.
        new Feed("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/cn/http.txt", "http"),
        new Feed("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/cn/https.txt", "http"),
        new Feed("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/by-country/cn/socks5.txt", "socks5"),
    };

    private static final LinkedHashMap<String, Candidate> CANDIDATES = new LinkedHashMap<>();
    private static final Map<String, Long> FAILED_UNTIL = new LinkedHashMap<>();
    private static boolean bootstrapLoaded;
    private static boolean refreshingFeeds;
    private static long lastFeedRefresh;
    private static long directCheckedAt;
    private static boolean directHealthy;
    private static Candidate lastGood;
    private static long lastGoodAt;

    static boolean isCloudflareUrl(String value) {
        if (value == null) return false;
        try {
            URL url = new URL(value.trim());
            return "https".equalsIgnoreCase(url.getProtocol())
                && url.getHost().toLowerCase(java.util.Locale.ROOT).endsWith(".workers.dev")
                && url.getUserInfo() == null
                && (url.getPort() == -1 || url.getPort() == 443)
                && (url.getPath().isEmpty() || "/".equals(url.getPath()))
                && url.getQuery() == null && url.getRef() == null;
        } catch (Exception ignored) {
            return false;
        }
    }

    static final class ApiResponse {
        final int status;
        final JSONObject body;
        final String route;
        ApiResponse(int status, JSONObject body, String route) {
            this.status = status;
            this.body = body;
            this.route = route;
        }
    }

    private static final class Candidate {
        final String protocol;
        final String ip;
        final int port;
        Candidate(String protocol, String ip, int port) {
            this.protocol = protocol;
            this.ip = ip;
            this.port = port;
        }
        String key() { return protocol + "://" + ip + ":" + port; }
        Proxy proxy() {
            Proxy.Type type = "socks5".equals(protocol) ? Proxy.Type.SOCKS : Proxy.Type.HTTP;
            return new Proxy(type, new InetSocketAddress(ip, port));
        }
    }

    static ApiResponse request(
        Context context,
        String baseUrl,
        String method,
        String path,
        JSONObject body,
        String token
    ) throws Exception {
        if (!isCloudflareUrl(baseUrl)) throw new IllegalArgumentException("Cloudflare 账号地址必须是 HTTPS workers.dev 地址");
        if (path == null || !path.startsWith("/v1/") || path.contains("..") || path.contains("#")) {
            throw new IllegalArgumentException("账号 API 路径无效");
        }
        if (!"GET".equals(method) && !"POST".equals(method)) {
            throw new IllegalArgumentException("账号 API 方法不受支持");
        }

        Route route = chooseRoute(context, baseUrl);
        URL endpoint = new URL(baseUrl.replaceAll("/+$", "") + path);
        String workerHost = endpoint.getHost();
        List<String> workerIps = resolveWorkerIpv4(workerHost);
        if (workerIps.isEmpty()) throw new java.io.IOException("Cloudflare Worker 没有可用的公网 IPv4 地址");

        String routeType = route.candidate == null ? "direct" : route.candidate.protocol;
        String routeHost = route.candidate == null ? "" : route.candidate.ip;
        int routePort = route.candidate == null ? 0 : route.candidate.port;
        String vpnStatus = AdminAccountVpnService.startForTask(
            context, workerHost, join(workerIps), routeType, routeHost, routePort);
        if (!"OK".equals(vpnStatus)) {
            throw new java.io.IOException("管理版内置 VPN 启动失败：" + vpnStatus);
        }

        HttpsURLConnection connection = null;
        try {
            // The admin app's Worker IPs now route through its own short-lived TUN.
            // Its local SOCKS bridge uses a protected upstream socket to avoid a TUN loop.
            connection = openHttps(endpoint, Proxy.NO_PROXY);
            connection.setRequestMethod(method);
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS + 3000);
            connection.setReadTimeout(10000);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Cache-Control", "no-store");
            if (token != null && !token.isEmpty()) {
                connection.setRequestProperty("Authorization", "Bearer " + token);
            }
            if (body != null) {
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                if (bytes.length > 65536) throw new IllegalArgumentException("账号请求数据超过限制");
                try (java.io.OutputStream output = connection.getOutputStream()) {
                    output.write(bytes);
                }
            }

            int status = connection.getResponseCode();
            InputStream input = status >= 200 && status < 400
                ? connection.getInputStream() : connection.getErrorStream();
            byte[] bytes = readBounded(input, 256 * 1024);
            JSONObject parsed = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
            if (route.candidate != null) markGood(route.candidate);
            return new ApiResponse(status, parsed, "内置 VPN · " + route.label());
        } catch (Exception error) {
            if (route.candidate != null) {
                markBad(route.candidate);
            } else {
                synchronized (LOCK) {
                    directHealthy = false;
                    directCheckedAt = 0;
                }
            }
            // Never retry a submitted POST: a read timeout may happen after the
            // Worker has already processed a ban/unban operation.
            throw new java.io.IOException(
                "Cloudflare 请求中断；为防止重复提交，本次不会自动重放。连接路径：" + route.label(),
                error
            );
        } finally {
            if (connection != null) connection.disconnect();
            String stopped = AdminAccountVpnService.stopForTask(context);
            if (!"OK".equals(stopped)) {
                android.util.Log.w("EffectCraftAdminVPN", "VPN stop confirmation: " + stopped);
            }
        }
    }

    private static List<String> resolveWorkerIpv4(String host) throws Exception {
        ArrayList<String> result = new ArrayList<>();
        for (InetAddress address : InetAddress.getAllByName(host)) {
            if (!(address instanceof Inet4Address) || address.isAnyLocalAddress()
                || address.isLoopbackAddress() || address.isLinkLocalAddress()
                || address.isSiteLocalAddress() || address.isMulticastAddress()) continue;
            String value = address.getHostAddress();
            if (!result.contains(value)) result.add(value);
            if (result.size() >= 16) break;
        }
        return result;
    }

    private static String join(List<String> values) {
        StringBuilder result = new StringBuilder();
        for (String value : values) {
            if (result.length() > 0) result.append(',');
            result.append(value);
        }
        return result.toString();
    }

    private static final class Route {
        final Proxy proxy;
        final Candidate candidate;
        Route(Proxy proxy, Candidate candidate) {
            this.proxy = proxy;
            this.candidate = candidate;
        }
        String label() { return candidate == null ? "Cloudflare 直连" : "公开 TLS 隧道（" + candidate.protocol + "）"; }
    }

    private static Route chooseRoute(Context context, String baseUrl) throws Exception {
        long now = System.currentTimeMillis();
        synchronized (LOCK) {
            loadBootstrapLocked(context);
            if (now - directCheckedAt < DIRECT_TTL_MS && directHealthy) {
                return new Route(Proxy.NO_PROXY, null);
            }
        }

        // Probe only TCP / proxy CONNECT reachability here. Do not call Worker
        // /health per candidate: the actual account API request below is the one
        // and only Cloudflare Worker invocation for this operation.
        boolean directOk = directTransportAvailable(baseUrl, 443);
        synchronized (LOCK) {
            directCheckedAt = System.currentTimeMillis();
            directHealthy = directOk;
        }
        if (directOk) return new Route(Proxy.NO_PROXY, null);

        refreshFeeds(context);
        List<Candidate> candidates = candidateSnapshot();
        int tried = 0;
        for (Candidate candidate : candidates) {
            if (tried++ >= MAX_TRIES) break;
            if (proxyTransportAvailable(candidate, baseUrl, 443)) {
                synchronized (LOCK) {
                    lastGood = candidate;
                    lastGoodAt = System.currentTimeMillis();
                    FAILED_UNTIL.remove(candidate.key());
                }
                return new Route(candidate.proxy(), candidate);
            }
            markBad(candidate);
        }

        throw new java.io.IOException("Cloudflare 直连失败，当前公开代理批次无法建立到账号服务的 TCP/TLS 隧道。请稍后重试。");
    }

    private static boolean directTransportAvailable(String baseUrl, int port) {
        try {
            URL url = new URL(baseUrl);
            InetAddress[] addresses = InetAddress.getAllByName(url.getHost());
            for (int i = 0; i < Math.min(addresses.length, 4); i++) {
                try (Socket socket = new Socket()) {
                    socket.connect(new InetSocketAddress(addresses[i], port), CONNECT_TIMEOUT_MS);
                    return true;
                } catch (Exception ignored) {}
            }
        } catch (Exception ignored) {}
        return false;
    }

    private static boolean proxyTransportAvailable(Candidate candidate, String host, int port) {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(candidate.ip, candidate.port), CONNECT_TIMEOUT_MS);
            socket.setSoTimeout(READ_TIMEOUT_MS);
            DataInputStream input = new DataInputStream(socket.getInputStream());
            DataOutputStream output = new DataOutputStream(socket.getOutputStream());
            if ("http".equals(candidate.protocol)) {
                byte[] request = ("CONNECT " + host + ":" + port + " HTTP/1.1\r\n"
                    + "Host: " + host + ":" + port + "\r\n"
                    + "Proxy-Connection: keep-alive\r\n\r\n").getBytes(StandardCharsets.US_ASCII);
                output.write(request);
                output.flush();
                String status = readAsciiLine(input, 4096);
                if (status == null || !(status.startsWith("HTTP/1.0 200") || status.startsWith("HTTP/1.1 200"))) {
                    return false;
                }
                int total = status.length();
                String line;
                while ((line = readAsciiLine(input, 4096)) != null && !line.isEmpty()) {
                    total += line.length();
                    if (total > 16384) return false;
                }
                return line != null;
            }

            output.write(new byte[] {5, 1, 0});
            output.flush();
            int version = input.readUnsignedByte();
            int method = input.readUnsignedByte();
            if (version != 5 || method != 0) return false;

            byte[] hostBytes = host.getBytes(StandardCharsets.US_ASCII);
            if (hostBytes.length == 0 || hostBytes.length > 255) return false;
            output.writeByte(5);
            output.writeByte(1);
            output.writeByte(0);
            output.writeByte(3);
            output.writeByte(hostBytes.length);
            output.write(hostBytes);
            output.writeShort(port);
            output.flush();

            int responseVersion = input.readUnsignedByte();
            int reply = input.readUnsignedByte();
            input.readUnsignedByte(); // RSV
            int addressType = input.readUnsignedByte();
            if (responseVersion != 5 || reply != 0) return false;
            if (addressType == 1) input.skipBytes(4);
            else if (addressType == 4) input.skipBytes(16);
            else if (addressType == 3) input.skipBytes(input.readUnsignedByte());
            else return false;
            input.skipBytes(2);
            return true;
        } catch (Exception ignored) {
            return false;
        }
    }

    private static String readAsciiLine(DataInputStream input, int maxBytes) throws Exception {
        ByteArrayOutputStream line = new ByteArrayOutputStream();
        while (line.size() < maxBytes) {
            int value = input.read();
            if (value < 0) return line.size() == 0 ? null : line.toString("US-ASCII");
            if (value == '\n') {
                byte[] bytes = line.toByteArray();
                int length = bytes.length > 0 && bytes[bytes.length - 1] == '\r' ? bytes.length - 1 : bytes.length;
                return new String(bytes, 0, length, StandardCharsets.US_ASCII);
            }
            line.write(value);
        }
        throw new java.io.IOException("Proxy response line exceeds limit");
    }

    private static HttpsURLConnection openHttps(URL url, Proxy proxy) throws Exception {
        java.net.URLConnection opened = proxy == null ? url.openConnection() : url.openConnection(proxy);
        if (!(opened instanceof HttpsURLConnection)) throw new java.io.IOException("账号 API 未建立 HTTPS 连接");
        HttpsURLConnection connection = (HttpsURLConnection) opened;
        // Leave Android's platform trust store and hostname verification untouched.
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        connection.setInstanceFollowRedirects(false);
        return connection;
    }

    private static void loadBootstrapLocked(Context context) {
        if (bootstrapLoaded) return;
        bootstrapLoaded = true;
        try (InputStream input = context.getAssets().open("public-proxy-bootstrap.txt")) {
            byte[] bytes = readBounded(input, 1024 * 1024);
            String lines = new String(bytes, StandardCharsets.UTF_8);
            for (String line : lines.split("\\r?\\n")) addCandidateLocked(parseCandidate(line));
        } catch (Exception ignored) {
            // Build without a Worker URL is still allowed; only Cloudflare mode
            // requires the bootstrap asset to be installed.
        }
    }

    private static void refreshFeeds(Context context) {
        long now = System.currentTimeMillis();
        synchronized (LOCK) {
            if (refreshingFeeds || now - lastFeedRefresh < FEED_REFRESH_MS) return;
            refreshingFeeds = true;
            lastFeedRefresh = now;
        }

        Thread refresher = new Thread(() -> {
            long deadline = System.currentTimeMillis() + 9000L;
            try {
                for (Feed feed : FEEDS) {
                    if (System.currentTimeMillis() >= deadline) break;
                    HttpURLConnection connection = null;
                    try {
                        connection = (HttpURLConnection) new URL(feed.url).openConnection(Proxy.NO_PROXY);
                        connection.setConnectTimeout(1800);
                        connection.setReadTimeout(2200);
                        connection.setRequestMethod("GET");
                        connection.setRequestProperty("Accept", "text/plain");
                        connection.setInstanceFollowRedirects(false);
                        if (connection.getResponseCode() != 200) continue;
                        byte[] bytes = readBounded(connection.getInputStream(), 1024 * 1024);
                        String body = new String(bytes, StandardCharsets.UTF_8);
                        int feedAdded = 0;
                        for (String line : body.split("\\r?\\n")) {
                            if (feedAdded >= MAX_PER_FEED) break;
                            Candidate candidate = parseCandidate(line, feed.defaultProtocol);
                            if (candidate == null) continue;
                            synchronized (LOCK) { addCandidateLocked(candidate); }
                            feedAdded++;
                        }
                    } catch (Exception ignored) {
                        // Keep last-known and build-time bootstrap entries on feed outages.
                    } finally {
                        if (connection != null) connection.disconnect();
                    }
                }
            } finally {
                synchronized (LOCK) {
                    refreshingFeeds = false;
                    lastFeedRefresh = System.currentTimeMillis();
                }
            }
        }, "EffectCraftProxyFeedRefresh");
        refresher.setDaemon(true);
        refresher.start();
    }

    private static List<Candidate> candidateSnapshot() {
        long now = System.currentTimeMillis();
        ArrayList<Candidate> result = new ArrayList<>();
        synchronized (LOCK) {
            if (lastGood != null && now - lastGoodAt < GOOD_TTL_MS) result.add(lastGood);
            for (Candidate candidate : CANDIDATES.values()) {
                if (result.contains(candidate)) continue;
                Long until = FAILED_UNTIL.get(candidate.key());
                if (until == null || until <= now) result.add(candidate);
            }
        }
        return result;
    }

    private static void addCandidateLocked(Candidate candidate) {
        if (candidate == null || CANDIDATES.containsKey(candidate.key())) return;
        if (CANDIDATES.size() < MAX_CANDIDATES) CANDIDATES.put(candidate.key(), candidate);
    }

    private static void markGood(Candidate candidate) {
        synchronized (LOCK) {
            lastGood = candidate;
            lastGoodAt = System.currentTimeMillis();
            FAILED_UNTIL.remove(candidate.key());
        }
    }

    private static void markBad(Candidate candidate) {
        synchronized (LOCK) {
            FAILED_UNTIL.put(candidate.key(), System.currentTimeMillis() + BAD_COOLDOWN_MS);
            if (candidate.equals(lastGood)) {
                lastGood = null;
                lastGoodAt = 0;
            }
        }
    }

    private static Candidate parseCandidate(String raw) {
        return parseCandidate(raw, "socks5");
    }

    private static Candidate parseCandidate(String raw, String defaultProtocol) {
        if (raw == null) return null;
        String line = raw.trim();
        if (line.isEmpty() || line.startsWith("#") || line.length() > 160) return null;
        String protocol;
        String endpoint;
        int marker = line.indexOf("://");
        if (marker >= 0) {
            protocol = line.substring(0, marker).toLowerCase(java.util.Locale.ROOT);
            endpoint = line.substring(marker + 3);
        } else {
            protocol = defaultProtocol;
            endpoint = line;
        }
        if (!"http".equals(protocol) && !"socks5".equals(protocol) && !"socks5h".equals(protocol)) return null;
        if (endpoint.contains("@") || endpoint.contains("/") || endpoint.contains("?") || endpoint.contains("#") || endpoint.contains(" ")) return null;
        int colon = endpoint.lastIndexOf(':');
        if (colon <= 0 || colon == endpoint.length() - 1) return null;
        String ip = endpoint.substring(0, colon);
        int port;
        try { port = Integer.parseInt(endpoint.substring(colon + 1)); }
        catch (NumberFormatException ignored) { return null; }
        if (port < 1 || port > 65535) return null;
        try {
            InetAddress address = InetAddress.getByName(ip);
            if (!(address instanceof Inet4Address) || !isPublicIpv4(address.getAddress())) return null;
        } catch (Exception ignored) { return null; }
        return new Candidate("socks5h".equals(protocol) ? "socks5" : protocol, ip, port);
    }

    private static boolean isPublicIpv4(byte[] bytes) {
        if (bytes == null || bytes.length != 4) return false;
        int a = bytes[0] & 255, b = bytes[1] & 255, c = bytes[2] & 255;
        if (a == 0 || a == 10 || a == 127 || a >= 224) return false;
        if (a == 100 && b >= 64 && b <= 127) return false;
        if (a == 169 && b == 254) return false;
        if (a == 172 && b >= 16 && b <= 31) return false;
        if (a == 192 && b == 168) return false;
        if (a == 192 && b == 0) return false;
        if (a == 192 && b == 88 && c == 99) return false;
        if (a == 198 && (b == 18 || b == 19)) return false;
        if (a == 198 && b == 51 && c == 100) return false;
        if (a == 203 && b == 0 && c == 113) return false;
        return true;
    }

    private static byte[] readBounded(InputStream input, int limit) throws Exception {
        if (input == null) return new byte[0];
        try (InputStream stream = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int total = 0;
            int count;
            while ((count = stream.read(buffer)) > 0) {
                total += count;
                if (total > limit) throw new java.io.IOException("HTTP 响应超过大小限制");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }
}
