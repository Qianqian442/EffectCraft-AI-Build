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

    private static void ensureNotCancelled() throws InterruptedException {
        if (Thread.currentThread().isInterrupted()) {
            throw new InterruptedException("本次账号操作已取消");
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
        boolean vpnMayBeActive = false;

        try {
            ensureNotCancelled();
            String permissionStatus = AdminAccountVpnService.requestPermissionForTask(context);
            if (!"OK".equals(permissionStatus)) {
                throw new java.io.IOException("Android VPN 权限尚未就绪：" + permissionStatus);
            }
            ensureNotCancelled();

            // Establish a first, app-scoped WARP tunnel to Cloudflare's numeric DNS
            // endpoints. Set the cleanup guard before startup so partial starts are
            // stopped even when the service times out or the caller cancels.
            vpnMayBeActive = true;
            String bootstrapStatus = AdminAccountVpnService.startForTask(
                context, workerHost, CloudflareHttpsTransport.resolverAddressesForTunnel());
            if (!"OK".equals(bootstrapStatus)) {
                throw new java.io.IOException("Cloudflare DNS 引导隧道启动失败：" + bootstrapStatus);
            }
            ensureNotCancelled();

            java.util.List<java.net.InetAddress> workerAddresses =
                CloudflareHttpsTransport.resolveWorkerAddresses(workerHost);
            ensureNotCancelled();
            if (workerAddresses == null || workerAddresses.isEmpty()) {
                throw new java.io.IOException("Cloudflare DoH 没有返回可用的 Worker 公网地址");
            }

            String stoppedBootstrap = AdminAccountVpnService.stopForTask(context);
            vpnMayBeActive = false;
            if (!"OK".equals(stoppedBootstrap)) {
                throw new java.io.IOException("Cloudflare DNS 引导隧道未能确认关闭：" + stoppedBootstrap);
            }
            ensureNotCancelled();

            // Rebuild the split route for the actual Worker IPs. The account request
            // itself is sent only after this second tunnel reports connected.
            vpnMayBeActive = true;
            String vpnStatus = AdminAccountVpnService.startForTask(context, workerHost, workerAddresses);
            if (!"OK".equals(vpnStatus)) {
                throw new java.io.IOException("管理版 Cloudflare WARP 账号隧道启动失败：" + vpnStatus);
            }
            ensureNotCancelled();

            CloudflareHttpsTransport.Response response = CloudflareHttpsTransport.execute(
                workerHost,
                endpoint.getFile(),
                method,
                body,
                token,
                workerAddresses
            );
            ensureNotCancelled();
            JSONObject parsed;
            try {
                parsed = response.body.length == 0
                    ? new JSONObject()
                    : new JSONObject(new String(response.body, StandardCharsets.UTF_8));
            } catch (org.json.JSONException invalidJson) {
                throw new java.io.IOException("Cloudflare 账号服务返回了无法识别的数据", invalidJson);
            }
            return new ApiResponse(response.status, parsed, "Cloudflare WARP 直连（Cloudflare DoH）");
        } catch (InterruptedException cancelled) {
            Thread.currentThread().interrupt();
            throw new java.io.IOException("本次账号操作已取消，正在关闭 Cloudflare VPN", cancelled);
        } catch (Exception error) {
            String cause = error.getMessage() == null
                ? error.getClass().getSimpleName()
                : error.getMessage();
            throw new java.io.IOException(
                "Cloudflare 账号请求未完成；如涉及 POST，系统不会自动重复提交。原因：" + cause,
                error
            );
        } finally {
            if (vpnMayBeActive) {
                String stopped = AdminAccountVpnService.stopForTask(context);
                if (!"OK".equals(stopped)) {
                    android.util.Log.w("EffectCraftAdminWARP", "VPN cleanup confirmation: " + stopped);
                }
            }
        }
    }
}
