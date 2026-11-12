package com.qianqian.effectcraftadmin;

import android.util.Log;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Loopback-only bridge from the native libp2p request-response stream to the admin phone's SQLite API. */
final class P2PAccountBridge {
    private static final String TAG = "EffectCraftAccountP2P";
    private static final int PORT = 8788;
    private static final int MAX_PACKET = 1_200_000;
    // The foreground Service keeps the process alive; bridge workers should
    // not keep a stopped service or the Robolectric test worker alive.
    private static final ExecutorService clients = Executors.newFixedThreadPool(6, runnable -> {
        Thread thread = new Thread(runnable, "EffectCraft-P2P-Account-Bridge-Client");
        thread.setDaemon(true);
        return thread;
    });
    private static volatile LanAccountServer accountServer;
    private static volatile ServerSocket listenerSocket;
    private static volatile boolean started;

    private P2PAccountBridge() {}

    static synchronized void start(LanAccountServer server) {
        accountServer = server;
        if (started) return;
        try {
            // Bind synchronously so the native P2P node is never advertised before
            // the local SQLite forwarding endpoint is actually listening.
            ServerSocket listener = new ServerSocket(PORT, 32, InetAddress.getByName("127.0.0.1"));
            listenerSocket = listener;
            started = true;
            Thread worker = new Thread(() -> listen(listener), "EffectCraft-P2P-Account-Bridge");
            worker.setDaemon(true);
            worker.start();
        } catch (Exception error) {
            started = false;
            Log.e(TAG, "Loopback account bridge bind failed", error);
        }
    }

    static synchronized void stop() {
        started = false;
        accountServer = null;
        ServerSocket current = listenerSocket;
        listenerSocket = null;
        if (current != null) {
            try { current.close(); } catch (Exception ignored) {}
        }
    }

    private static void listen(ServerSocket listener) {
        try (ServerSocket server = listener) {
            while (started && listenerSocket == server) {
                Socket socket = server.accept();
                clients.execute(() -> handle(socket));
            }
        } catch (Exception error) {
            if (started && listenerSocket == listener) {
                Log.e(TAG, "Loopback account bridge failed", error);
            }
        } finally {
            if (listenerSocket == listener) {
                listenerSocket = null;
                started = false;
                accountServer = null;
            }
        }
    }

    private static void handle(Socket socket) {
        try (Socket client = socket) {
            client.setSoTimeout(15000);
            try {
                InputStream in = client.getInputStream();
                ByteArrayOutputStream packet = new ByteArrayOutputStream();
                int value;
                while ((value = in.read()) != -1 && value != '\n') {
                    if (packet.size() >= MAX_PACKET) throw new IllegalArgumentException("请求内容过大");
                    packet.write(value);
                }
                if (value == -1) throw new IllegalArgumentException("账号请求没有以换行符结束");
                LanAccountServer server = accountServer;
                if (server == null) throw new IllegalStateException("管理员账号数据库尚未启动");
                JSONObject response = server.handleP2PRequest(packet.toString(StandardCharsets.UTF_8.name()));
                writeEnvelope(client.getOutputStream(), response);
            } catch (Exception error) {
                Log.w(TAG, "Account RPC packet rejected: " + error.getMessage());
                try {
                    JSONObject detail = new JSONObject();
                    detail.put("detail", error.getMessage() == null ? "账号请求无法处理" : error.getMessage());
                    JSONObject envelope = new JSONObject();
                    envelope.put("status", 400);
                    envelope.put("body", detail.toString());
                    writeEnvelope(client.getOutputStream(), envelope);
                } catch (Exception writeError) {
                    Log.w(TAG, "Could not return account RPC error response: " + writeError.getMessage());
                }
            }
        } catch (Exception error) {
            Log.w(TAG, "Loopback account bridge connection failed: " + error.getMessage());
        }
    }

    private static void writeEnvelope(OutputStream out, JSONObject envelope) throws Exception {
        byte[] wire = (envelope.toString() + "\n").getBytes(StandardCharsets.UTF_8);
        out.write(wire);
        out.flush();
    }
}
