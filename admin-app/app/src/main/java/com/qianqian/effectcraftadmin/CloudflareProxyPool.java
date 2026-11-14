package com.qianqian.effectcraftadmin;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.Proxy;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

import javax.net.ssl.HttpsURLConnection;

/**
 * Direct Cloudflare account API transport.
 *
 * Every account request requires a live task-scoped Cloudflare WARP/MASQUE
 * tunnel. No public proxy or administrator-phone relay is used. TLS hostname
 * and certificate verification remain enabled with Android's default trust.
 */
final class CloudflareProxyPool {
    private static final int CONNECT_TIMEOUT_MS = 15000;
    private static final int READ_TIMEOUT_MS = 12000;
    private static final int MAX_RESPONSE_BYTES = 256 * 1024;

    private CloudflareProxyPool() {}

    static boolean isCloudflareUrl(String value) {
        if (value == null) return false;
        try {
            URL url = new URL(value.trim());
            return "https".equalsIgnoreCase(url.getProtocol())
                && url.getHost().toLowerCase(Locale.ROOT).endsWith(".workers.dev")
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

    static ApiResponse request(
        Context context,
        String baseUrl,
        String method,
        String path,
        JSONObject body,
        String token
    ) throws Exception {
        if (!isCloudflareUrl(baseUrl)) {
            throw new IllegalArgumentException("Cloudflare 账号地址必须是 HTTPS workers.dev 地址");
        }
        if (path == null || !path.startsWith("/v1/") || path.contains("..") || path.contains("#")) {
            throw new IllegalArgumentException("账号 API 路径无效");
        }
        if (!"GET".equals(method) && !"POST".equals(method)) {
            throw new IllegalArgumentException("账号 API 方法不受支持");
        }

        URL endpoint = new URL(baseUrl.replaceAll("/+$", "") + path);
        String workerHost = endpoint.getHost();
        String vpnStatus = AdminAccountVpnService.startForTask(context, workerHost);
        if (!"OK".equals(vpnStatus)) {
            throw new java.io.IOException("管理版 Cloudflare WARP 启动失败：" + vpnStatus);
        }

        HttpsURLConnection connection = null;
        try {
            // The app's Worker IP routes use the MASQUE TUN. Proxy.NO_PROXY is
            // deliberate: the request must not silently fall back to a relay.
            connection = openHttps(endpoint);
            connection.setRequestMethod(method);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Cache-Control", "no-store");
            connection.setRequestProperty("Connection", "close");
            connection.setUseCaches(false);

            if (token != null && !token.isEmpty()) {
                connection.setRequestProperty("Authorization", "Bearer " + token);
            }
            if (body != null) {
                byte[] requestBytes = body.toString().getBytes(StandardCharsets.UTF_8);
                if (requestBytes.length > 65536) {
                    throw new IllegalArgumentException("账号请求数据超过限制");
                }
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                try (java.io.OutputStream output = connection.getOutputStream()) {
                    output.write(requestBytes);
                }
            }

            int status = connection.getResponseCode();
            InputStream input = status >= 200 && status < 400
                ? connection.getInputStream() : connection.getErrorStream();
            byte[] responseBytes = readBounded(input, MAX_RESPONSE_BYTES);
            JSONObject parsed;
            try {
                parsed = responseBytes.length == 0
                    ? new JSONObject()
                    : new JSONObject(new String(responseBytes, StandardCharsets.UTF_8));
            } catch (org.json.JSONException invalidJson) {
                throw new java.io.IOException("Cloudflare 账号服务返回了无法识别的数据", invalidJson);
            }
            return new ApiResponse(status, parsed, "Cloudflare WARP 直连");
        } catch (Exception error) {
            // Never retry a POST: the Worker may have applied a ban/unban before
            // a response interruption. Do not risk submitting the same action twice.
            String cause = error.getMessage() == null
                ? error.getClass().getSimpleName()
                : error.getMessage();
            throw new java.io.IOException(
                "Cloudflare WARP 请求中断；为防止重复提交，本次不会自动重放。原因：" + cause,
                error
            );
        } finally {
            if (connection != null) connection.disconnect();
            String stopped = AdminAccountVpnService.stopForTask(context);
            if (!"OK".equals(stopped)) {
                android.util.Log.w("EffectCraftAdminWARP", "VPN stop confirmation: " + stopped);
            }
        }
    }

    private static HttpsURLConnection openHttps(URL endpoint) throws Exception {
        java.net.URLConnection opened = endpoint.openConnection(Proxy.NO_PROXY);
        if (!(opened instanceof HttpsURLConnection)) {
            throw new java.io.IOException("账号 API 未建立 HTTPS 连接");
        }
        HttpsURLConnection connection = (HttpsURLConnection) opened;
        // Keep the platform certificate chain and hostname verification intact.
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        connection.setInstanceFollowRedirects(false);
        return connection;
    }

    private static byte[] readBounded(InputStream input, int limit) throws Exception {
        if (input == null) return new byte[0];
        try (InputStream in = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int total = 0;
            int read;
            while ((read = in.read(buffer)) != -1) {
                total += read;
                if (total > limit) throw new java.io.IOException("Cloudflare 响应超过大小限制");
                output.write(buffer, 0, read);
            }
            return output.toByteArray();
        }
    }
}
