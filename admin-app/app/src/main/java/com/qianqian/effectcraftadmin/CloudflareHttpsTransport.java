package com.qianqian.effectcraftadmin;

import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.Inet4Address;
import java.net.Inet6Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import javax.net.ssl.SNIHostName;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLSession;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/**
 * Direct, certificate-verified Cloudflare HTTPS transport for the account Worker.
 *
 * Worker DNS is obtained from Cloudflare DoH over TCP/443 using numeric resolver
 * addresses. The Worker connection is then opened to those authenticated DNS
 * answers while retaining the real Worker hostname for TLS SNI, certificate
 * hostname verification and the HTTP Host header. No proxy or relay is used.
 */
final class CloudflareHttpsTransport {
    private static final String DNS_HOST = "cloudflare-dns.com";
    private static final int CONNECT_TIMEOUT_MS = 15000;
    private static final int READ_TIMEOUT_MS = 12000;
    private static final int MAX_RESPONSE_BYTES = 256 * 1024;
    private static final int MAX_HEADER_LINE_BYTES = 16 * 1024;
    private static final int MAX_DNS_ADDRESSES = 16;

    private static final List<InetAddress> CLOUDFLARE_DOH_IPS = createResolverAddresses();

    private CloudflareHttpsTransport() {}

    static final class Response {
        final int status;
        final byte[] body;

        Response(int status, byte[] body) {
            this.status = status;
            this.body = body == null ? new byte[0] : body;
        }
    }

    static List<InetAddress> resolveWorkerAddresses(String host) throws Exception {
        if (!isValidHost(host)) {
            throw new IllegalArgumentException("账号服务器域名无效");
        }

        Set<InetAddress> resolved = new LinkedHashSet<>();
        Exception lastError = null;
        for (int type : new int[] {1, 28}) {
            String target = "/dns-query?name="
                + URLEncoder.encode(host, "UTF-8")
                + "&type=" + type;
            try {
                byte[] bytes = requestJson(DNS_HOST, CLOUDFLARE_DOH_IPS, target);
                JSONObject answer = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
                if (answer.optInt("Status", -1) != 0) continue;

                JSONArray records = answer.optJSONArray("Answer");
                if (records == null) continue;
                for (int i = 0; i < records.length() && resolved.size() < MAX_DNS_ADDRESSES; i++) {
                    JSONObject record = records.optJSONObject(i);
                    if (record == null || record.optInt("type", -1) != type) continue;
                    String value = record.optString("data", "").trim();
                    if (value.isEmpty()) continue;
                    InetAddress address = parseNumericAddress(value);
                    if (address == null || !isPublicAddress(address)) continue;
                    if (type == 1 && !(address instanceof Inet4Address)) continue;
                    if (type == 28 && !(address instanceof Inet6Address)) continue;
                    resolved.add(address);
                }
            } catch (Exception error) {
                lastError = error;
            }
        }

        if (resolved.isEmpty()) {
            String detail = lastError == null ? "Cloudflare DNS 没有返回可用的公网 A/AAAA 记录"
                : (lastError.getMessage() == null ? lastError.getClass().getSimpleName() : lastError.getMessage());
            throw new IOException("无法通过 Cloudflare 加密 DNS 确认账号服务器地址：" + detail, lastError);
        }
        return new ArrayList<>(resolved);
    }

    static Response execute(
        String workerHost,
        String requestTarget,
        String method,
        JSONObject body,
        String token,
        List<InetAddress> workerAddresses
    ) throws Exception {
        if (!isValidHost(workerHost) || workerAddresses == null || workerAddresses.isEmpty()) {
            throw new IOException("Cloudflare Worker 的可信地址列表为空");
        }
        if (requestTarget == null || !requestTarget.startsWith("/v1/")
            || requestTarget.contains("..") || requestTarget.contains("#")
            || requestTarget.contains("\r") || requestTarget.contains("\n")) {
            throw new IllegalArgumentException("账号 API 路径无效");
        }
        if (!"GET".equals(method) && !"POST".equals(method)) {
            throw new IllegalArgumentException("账号 API 方法不受支持");
        }

        byte[] requestBody = body == null ? new byte[0] : body.toString().getBytes(StandardCharsets.UTF_8);
        if (requestBody.length > 65536) {
            throw new IllegalArgumentException("账号请求数据超过限制");
        }

        // Only connect/TLS failures may advance to another authenticated DNS
        // answer. Once any HTTP bytes are written, the POST is never replayed.
        SSLSocket socket = openTlsSocket(workerHost, workerAddresses);
        try {
            OutputStream output = socket.getOutputStream();
            StringBuilder headers = new StringBuilder(512);
            headers.append(method).append(' ').append(requestTarget).append(" HTTP/1.1\r\n");
            headers.append("Host: ").append(workerHost).append("\r\n");
            headers.append("Accept: application/json\r\n");
            headers.append("Cache-Control: no-store\r\n");
            headers.append("Connection: close\r\n");
            headers.append("Accept-Encoding: identity\r\n");
            if (token != null && !token.isEmpty()) {
                if (token.indexOf('\r') >= 0 || token.indexOf('\n') >= 0) {
                    throw new IllegalArgumentException("账号令牌格式无效");
                }
                headers.append("Authorization: Bearer ").append(token).append("\r\n");
            }
            if (body != null) {
                headers.append("Content-Type: application/json; charset=utf-8\r\n");
            }
            if (requestBody.length > 0) {
                headers.append("Content-Length: ").append(requestBody.length).append("\r\n");
            }
            headers.append("\r\n");
            output.write(headers.toString().getBytes(StandardCharsets.US_ASCII));
            if (requestBody.length > 0) output.write(requestBody);
            output.flush();

            return readResponse(socket.getInputStream());
        } finally {
            try { socket.close(); } catch (IOException ignored) {}
        }
    }

    private static byte[] requestJson(String host, List<InetAddress> addresses, String target) throws Exception {
        Exception lastError = null;
        for (InetAddress address : addresses) {
            SSLSocket socket = null;
            try {
                socket = openTlsSocket(host, Collections.singletonList(address));
                OutputStream output = socket.getOutputStream();
                String request = "GET " + target + " HTTP/1.1\r\n"
                    + "Host: " + host + "\r\n"
                    + "Accept: application/dns-json\r\n"
                    + "Cache-Control: no-store\r\n"
                    + "Connection: close\r\n"
                    + "Accept-Encoding: identity\r\n\r\n";
                output.write(request.getBytes(StandardCharsets.US_ASCII));
                output.flush();

                Response response = readResponse(socket.getInputStream());
                if (response.status != 200) {
                    throw new IOException("Cloudflare DoH 返回 HTTP " + response.status);
                }
                return response.body;
            } catch (Exception error) {
                lastError = error;
            } finally {
                if (socket != null) {
                    try { socket.close(); } catch (IOException ignored) {}
                }
            }
        }
        throw new IOException("无法直连 Cloudflare DNS over HTTPS: "
            + (lastError == null ? "no resolver available" : lastError.getMessage()), lastError);
    }

    private static SSLSocket openTlsSocket(String host, List<InetAddress> addresses) throws Exception {
        Exception lastError = null;
        SSLSocketFactory factory = (SSLSocketFactory) SSLSocketFactory.getDefault();
        for (InetAddress address : addresses) {
            Socket underlay = new Socket();
            try {
                underlay.connect(new InetSocketAddress(address, 443), CONNECT_TIMEOUT_MS);
                SSLSocket tls = (SSLSocket) factory.createSocket(underlay, host, 443, true);
                tls.setSoTimeout(READ_TIMEOUT_MS);

                SSLParameters parameters = tls.getSSLParameters();
                parameters.setEndpointIdentificationAlgorithm("HTTPS");
                parameters.setServerNames(Collections.singletonList(new SNIHostName(host)));
                if (Build.VERSION.SDK_INT >= 29) {
                    parameters.setApplicationProtocols(new String[] {"http/1.1"});
                }
                tls.setSSLParameters(parameters);
                tls.startHandshake();

                // Keep a second explicit hostname check in addition to the TLS
                // endpoint-identification algorithm for Android provider parity.
                SSLSession session = tls.getSession();
                if (!javax.net.ssl.HttpsURLConnection.getDefaultHostnameVerifier().verify(host, session)) {
                    throw new IOException("TLS 证书主机名与 " + host + " 不匹配");
                }
                String protocol = Build.VERSION.SDK_INT >= 29 ? tls.getApplicationProtocol() : "";
                if (protocol != null && !protocol.isEmpty() && !"http/1.1".equals(protocol)) {
                    throw new IOException("Cloudflare TLS 协商了不支持的 HTTP 协议：" + protocol);
                }
                return tls;
            } catch (Exception error) {
                lastError = error;
                try { underlay.close(); } catch (IOException ignored) {}
            }
        }
        throw new IOException("无法通过可信 Cloudflare DNS 地址建立 HTTPS/TLS：" +
            (lastError == null ? "没有可连接地址" : lastError.getMessage()), lastError);
    }

    private static Response readResponse(InputStream rawInput) throws Exception {
        BufferedInputStream input = new BufferedInputStream(rawInput, 8192);
        String statusLine = readLine(input);
        if (statusLine == null || !statusLine.startsWith("HTTP/")) {
            throw new IOException("Cloudflare HTTPS 响应状态行无效");
        }
        String[] statusParts = statusLine.split(" ", 3);
        if (statusParts.length < 2) throw new IOException("Cloudflare HTTPS 响应缺少状态码");
        int status;
        try { status = Integer.parseInt(statusParts[1]); }
        catch (NumberFormatException invalid) { throw new IOException("Cloudflare HTTPS 状态码无效", invalid); }

        // Handle an informational response before the final response.
        while (status >= 100 && status < 200 && status != 101) {
            String line;
            do { line = readLine(input); } while (line != null && !line.isEmpty());
            statusLine = readLine(input);
            if (statusLine == null) throw new IOException("Cloudflare HTTPS 响应提前结束");
            statusParts = statusLine.split(" ", 3);
            if (statusParts.length < 2) throw new IOException("Cloudflare HTTPS 状态码无效");
            status = Integer.parseInt(statusParts[1]);
        }

        long contentLength = -1;
        boolean chunked = false;
        String line;
        while ((line = readLine(input)) != null && !line.isEmpty()) {
            int colon = line.indexOf(':');
            if (colon <= 0) continue;
            String name = line.substring(0, colon).trim().toLowerCase(Locale.ROOT);
            String value = line.substring(colon + 1).trim();
            if ("content-length".equals(name)) {
                try { contentLength = Long.parseLong(value); }
                catch (NumberFormatException invalid) { throw new IOException("Cloudflare Content-Length 无效", invalid); }
            } else if ("transfer-encoding".equals(name)
                && value.toLowerCase(Locale.ROOT).contains("chunked")) {
                chunked = true;
            }
        }

        if (status == 204 || status == 304) return new Response(status, new byte[0]);
        byte[] body;
        if (chunked) {
            body = readChunked(input);
        } else if (contentLength >= 0) {
            if (contentLength > MAX_RESPONSE_BYTES) throw new IOException("Cloudflare 响应超过大小限制");
            body = readExact(input, (int) contentLength);
        } else {
            body = readUntilEof(input);
        }
        return new Response(status, body);
    }

    private static byte[] readChunked(InputStream input) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        while (true) {
            String line = readLine(input);
            if (line == null) throw new IOException("Cloudflare chunked 响应提前结束");
            int semicolon = line.indexOf(';');
            String sizeText = (semicolon >= 0 ? line.substring(0, semicolon) : line).trim();
            long size;
            try { size = Long.parseLong(sizeText, 16); }
            catch (NumberFormatException invalid) { throw new IOException("Cloudflare chunk 长度无效", invalid); }
            if (size < 0 || size > MAX_RESPONSE_BYTES || output.size() + size > MAX_RESPONSE_BYTES) {
                throw new IOException("Cloudflare 响应超过大小限制");
            }
            if (size == 0) {
                while ((line = readLine(input)) != null && !line.isEmpty()) { /* trailers */ }
                break;
            }
            byte[] chunk = readExact(input, (int) size);
            output.write(chunk);
            int cr = input.read();
            int lf = input.read();
            if (cr != '\r' || lf != '\n') throw new IOException("Cloudflare chunk 结束标记无效");
        }
        return output.toByteArray();
    }

    private static byte[] readExact(InputStream input, int expected) throws IOException {
        byte[] data = new byte[expected];
        int offset = 0;
        while (offset < expected) {
            int count = input.read(data, offset, expected - offset);
            if (count < 0) throw new IOException("Cloudflare HTTPS 响应长度不足");
            offset += count;
        }
        return data;
    }

    private static byte[] readUntilEof(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (output.size() + count > MAX_RESPONSE_BYTES) {
                throw new IOException("Cloudflare 响应超过大小限制");
            }
            output.write(buffer, 0, count);
        }
        return output.toByteArray();
    }

    private static String readLine(InputStream input) throws IOException {
        ByteArrayOutputStream line = new ByteArrayOutputStream();
        int value;
        boolean sawAny = false;
        while ((value = input.read()) != -1) {
            sawAny = true;
            if (value == '\n') break;
            if (value != '\r') {
                line.write(value);
                if (line.size() > MAX_HEADER_LINE_BYTES) {
                    throw new IOException("Cloudflare HTTPS 响应头行超过限制");
                }
            }
        }
        if (!sawAny && line.size() == 0) return null;
        return line.toString("US-ASCII");
    }

    private static List<InetAddress> createResolverAddresses() {
        List<InetAddress> result = new ArrayList<>(2);
        try {
            result.add(InetAddress.getByAddress(new byte[] {1, 1, 1, 1}));
            result.add(InetAddress.getByAddress(new byte[] {1, 0, 0, 1}));
            return result;
        } catch (Exception impossible) {
            throw new ExceptionInInitializerError(impossible);
        }
    }

    private static InetAddress parseNumericAddress(String value) {
        try {
            if (!value.matches("[0-9.]+") && !value.contains(":")) return null;
            return InetAddress.getByName(value);
        } catch (Exception ignored) {
            return null;
        }
    }

    private static boolean isPublicAddress(InetAddress address) {
        if (address.isAnyLocalAddress() || address.isLoopbackAddress()
            || address.isLinkLocalAddress() || address.isSiteLocalAddress()
            || address.isMulticastAddress()) return false;
        if (address instanceof Inet4Address) {
            byte[] b = address.getAddress();
            int a = b[0] & 255, second = b[1] & 255;
            return a != 0 && a != 10 && a != 127 && a < 224
                && !(a == 100 && second >= 64 && second <= 127)
                && !(a == 169 && second == 254)
                && !(a == 172 && second >= 16 && second <= 31)
                && !(a == 192 && second == 168)
                && !(a == 192 && second == 0)
                && !(a == 198 && (second == 18 || second == 19 || second == 51))
                && !(a == 203 && second == 0 && (b[2] & 255) == 113);
        }
        if (address instanceof Inet6Address) {
            byte[] b = address.getAddress();
            return (b[0] & 0xfe) != 0xfc;
        }
        return false;
    }

    private static boolean isValidHost(String host) {
        return host != null && host.length() <= 253 && host.length() > 0
            && host.matches("[A-Za-z0-9.-]+")
            && !host.startsWith(".") && !host.endsWith(".") && !host.contains("..");
    }
}
