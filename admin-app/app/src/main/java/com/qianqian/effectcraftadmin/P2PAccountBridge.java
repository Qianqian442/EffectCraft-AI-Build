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
    private static final ExecutorService clients = Executors.newFixedThreadPool(6);
    private static volatile LanAccountServer accountServer;
    private static volatile boolean started;

    private P2PAccountBridge() {}

    static synchronized void start(LanAccountServer server) {
        accountServer = server;
        if (started) return;
        try {
            // Bind synchronously so the native P2P node is never advertised before
            // the local SQLite forwarding endpoint is actually listening.
            ServerSocket listener = new ServerSocket(PORT, 32, InetAddress.getByName("127.0.0.1"));
            started = true;
            Thread worker = new Thread(() -> listen(listener), "EffectCraft-P2P-Account-Bridge");
            worker.setDaemon(true);
            worker.start();
        } catch (Exception error) {
            started = false;
            Log.e(TAG, "Loopback account bridge bind failed", error);
        }
    }

    private static void listen(ServerSocket listener) {
        try (ServerSocket server = listener) {
            while (true) {
                Socket socket = server.accept();
                clients.execute(() -> handle(socket));
            }
        } catch (Exception error) {
            started = false;
            Log.e(TAG, "Loopback account bridge failed", error);
        }
    }

    private static void handle(Socket socket) {
        try (Socket client = socket) {
            client.setSoTimeout(15000);
            InputStream in = client.getInputStream();
            ByteArrayOutputStream packet = new ByteArrayOutputStream();
            int value;
            while ((value = in.read()) != -1 && value != '\n') {
                if (packet.size() >= MAX_PACKET) throw new IllegalArgumentException("请求内容过大");
                packet.write(value);
            }
            LanAccountServer server = accountServer;
            if (server == null) throw new IllegalStateException("管理员账号数据库尚未启动");
            JSONObject response = server.handleP2PRequest(packet.toString(StandardCharsets.UTF_8.name()));
            byte[] wire = (response.toString() + "\n").getBytes(StandardCharsets.UTF_8);
            OutputStream out = client.getOutputStream();
            out.write(wire);
            out.flush();
        } catch (Exception error) {
            Log.w(TAG, "Account RPC packet rejected: " + error.getMessage());
        }
    }
}
