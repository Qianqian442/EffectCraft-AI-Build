package com.qianqian.effectcraftadmin;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * Minimal LAN node endpoint. It intentionally does not open the account database,
 * hash passwords, issue admin tokens, or store account records. Account operations
 * remain on the authenticated account API; this listener only answers health probes.
 */
final class PeerHealthServer implements Runnable {
    static final int PORT = 8787;
    private volatile boolean running = true;
    private volatile ServerSocket listener;
    private volatile String boundIp = "";

    static String getWifiIpv4() { return LanAccountServer.getWifiIpv4(); }

    @Override public void run() {
        while (running) {
            String ip = getWifiIpv4();
            if (ip.isEmpty()) { sleep(2500); continue; }
            try (ServerSocket server = new ServerSocket()) {
                server.setReuseAddress(true);
                server.bind(new InetSocketAddress(InetAddress.getByName(ip), PORT), 8);
                server.setSoTimeout(2000);
                listener = server;
                boundIp = ip;
                while (running && ip.equals(getWifiIpv4())) {
                    try (Socket socket = server.accept()) {
                        socket.setSoTimeout(1500);
                        handle(socket);
                    } catch (java.net.SocketTimeoutException ignored) {
                        // Recheck Wi-Fi state without polling aggressively.
                    } catch (Exception ignored) {
                        // A malformed or disconnected peer must not stop the node.
                    }
                }
            } catch (Exception ignored) {
                sleep(2500);
            } finally {
                listener = null;
                boundIp = "";
            }
        }
    }

    private void handle(Socket socket) throws Exception {
        InetAddress remote = socket.getInetAddress();
        if (remote == null || (!remote.isLoopbackAddress() && !remote.isSiteLocalAddress())) {
            respond(socket, 403, "{\"ok\":false}");
            return;
        }
        BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.US_ASCII));
        String requestLine = reader.readLine();
        if (requestLine == null || requestLine.length() > 2048) { respond(socket, 400, "{\"ok\":false}"); return; }
        String[] parts = requestLine.split(" ");
        String line;
        int headerBytes = requestLine.length();
        while ((line = reader.readLine()) != null && !line.isEmpty()) {
            headerBytes += line.length();
            if (headerBytes > 8192) { respond(socket, 431, "{\"ok\":false}"); return; }
        }
        if (parts.length >= 2 && "GET".equalsIgnoreCase(parts[0]) && "/health".equals(parts[1])) {
            respond(socket, 200, "{\"ok\":true,\"service\":\"EffectCraft-P2P-Node\",\"role\":\"discovery-only\"}");
        } else if (parts.length >= 2 && "GET".equalsIgnoreCase(parts[0]) && "/peer/info".equals(parts[1])) {
            respond(socket, 200, "{\"ok\":true,\"protocol\":1}");
        } else {
            respond(socket, 404, "{\"ok\":false,\"error\":\"not_found\"}");
        }
    }

    private static void respond(Socket socket, int status, String body) throws Exception {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        String reason = status == 200 ? "OK" : status == 403 ? "Forbidden" : status == 404 ? "Not Found" : status == 431 ? "Request Header Fields Too Large" : "Bad Request";
        String header = String.format(Locale.ROOT,
            "HTTP/1.1 %d %s\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: %d\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
            status, reason, bytes.length);
        OutputStream out = socket.getOutputStream();
        out.write(header.getBytes(StandardCharsets.US_ASCII));
        out.write(bytes);
        out.flush();
    }

    static String getBoundIp() { return ""; }

    void stopServer() {
        running = false;
        ServerSocket current = listener;
        if (current != null) try { current.close(); } catch (Exception ignored) { }
    }

    private static void sleep(long millis) {
        try { Thread.sleep(millis); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }
}
