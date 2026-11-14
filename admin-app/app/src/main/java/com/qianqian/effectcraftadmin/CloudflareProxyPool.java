package com.qianqian.effectcraftadmin;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Proxy;
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
    private static final int MAX_TRIES = 8;
    private static final int CONNECT_TIMEOUT_MS = 2200;
    private static final int READ_TIMEOUT_MS = 3500;

    private static final String[] FEEDS = new String[] {
        "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/cn.txt",
        "https://proxy-scraper.de/country/cn/proxies.txt",
        "https://cdn.jsdelivr.net/gh/maximilianfeix/free-proxy-list@main/countries/cn.txt",
        "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/hk.txt",
        "https://proxy-scraper.de/country/hk/proxies.txt",
        "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/jp.txt",
        "https://proxy-scraper.de/country/jp/proxies.txt",
        "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/countries/sg.txt",
        "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/https.txt",
        "https://proxy-scraper.de/https.txt",
        "https://raw.githubusercontent.com/maximilianfeix/free-proxy-list/main/socks5.txt",
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
        HttpsURLConnection connection = null;
        try {
            connection = openHttps(endpoint, route.proxy);
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
            return new ApiResponse(status, parsed, route.label());
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
            // Worker has already processed a registration, ban or profile update.
            throw new java.io.IOException(
                "Cloudflare 请求中断；为防止重复提交，本次不会自动重放。连接路径：" + route.label(),
                error
            );
        } finally {
            if (connection != null) connection.disconnect();
        }
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

        boolean directOk = false;
        try {
            directOk = workerHealthy(baseUrl, Proxy.NO_PROXY);
        } catch (Exception ignored) {}
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
            boolean healthy = false;
            try {
                healthy = workerHealthy(baseUrl, candidate.proxy());
            } catch (Exception ignored) {}
            if (healthy) {
                synchronized (LOCK) {
                    lastGood = candidate;
                    lastGoodAt = System.currentTimeMillis();
                    FAILED_UNTIL.remove(candidate.key());
                }
                return new Route(candidate.proxy(), candidate);
            }
            markBad(candidate);
        }

        throw new java.io.IOException("Cloudflare 直连失败，公开代理池暂时没有通过真实 HTTPS/TLS 检查的节点。请稍后重试。");
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

    private static boolean workerHealthy(String baseUrl, Proxy proxy) throws Exception {
        URL health = new URL(baseUrl.replaceAll("/+$", "") + "/health");
        HttpsURLConnection connection = null;
        try {
            connection = openHttps(health, proxy);
            connection.setRequestMethod("GET");
            connection.setRequestProperty("Accept", "application/json");
            int status = connection.getResponseCode();
            if (status != 200) return false;
            JSONObject result = new JSONObject(new String(readBounded(connection.getInputStream(), 32 * 1024), StandardCharsets.UTF_8));
            return result.optBoolean("ok", false) && result.optBoolean("database", false);
        } finally {
            if (connection != null) connection.disconnect();
        }
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

        Context appContext = context.getApplicationContext();
        Thread refresher = new Thread(() -> {
            long deadline = System.currentTimeMillis() + 9000L;
            try {
                for (String feed : FEEDS) {
                    if (System.currentTimeMillis() >= deadline) break;
                    HttpURLConnection connection = null;
                    try {
                        connection = (HttpURLConnection) new URL(feed).openConnection(Proxy.NO_PROXY);
                        connection.setConnectTimeout(1800);
                        connection.setReadTimeout(2200);
                        connection.setRequestMethod("GET");
                        connection.setRequestProperty("Accept", "text/plain");
                        connection.setInstanceFollowRedirects(false);
                        if (connection.getResponseCode() != 200) continue;
                        byte[] bytes = readBounded(connection.getInputStream(), 1024 * 1024);
                        String body = new String(bytes, StandardCharsets.UTF_8);
                        for (String line : body.split("\\\\r?\\\\n")) {
                            Candidate candidate = parseCandidate(line);
                            if (candidate == null) continue;
                            synchronized (LOCK) { addCandidateLocked(candidate); }
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
            protocol = "socks5";
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
