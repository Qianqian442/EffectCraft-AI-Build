package com.qianqian.effectcraftadmin;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

/** Broadcast discovery for the administrator-phone account API on the current Wi-Fi. */
final class AccountDiscoveryServer implements Runnable {
    static final int PORT = 8789;
    private volatile boolean running = true;
    private volatile DatagramSocket socket;

    @Override public void run() {
        while (running) {
            try (DatagramSocket server = new DatagramSocket(null)) {
                server.setReuseAddress(true);
                server.setBroadcast(true);
                server.bind(new InetSocketAddress(PORT));
                socket = server;
                byte[] buffer = new byte[256];
                while (running) {
                    DatagramPacket packet = new DatagramPacket(buffer, buffer.length);
                    server.receive(packet);
                    String request = new String(packet.getData(), packet.getOffset(),
                        packet.getLength(), StandardCharsets.UTF_8);
                    if (!"EFFECTCRAFT_ACCOUNT_DISCOVER_V1".equals(request)) continue;
                    InetAddress remote = packet.getAddress();
                    if (!(remote instanceof Inet4Address) || !remote.isSiteLocalAddress()) continue;
                    String localIp = LanAccountServer.getWifiIpv4();
                    if (localIp.isEmpty()) continue;
                    byte[] data = ("EFFECTCRAFT_ACCOUNT_SERVER_V1|http://" + localIp + ":" +
                        LanAccountServer.PORT).getBytes(StandardCharsets.UTF_8);
                    server.send(new DatagramPacket(data, data.length, packet.getAddress(), packet.getPort()));
                }
            } catch (Exception ignored) {
                if (running) {
                    try { Thread.sleep(1500); }
                    catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                }
            } finally {
                socket = null;
            }
        }
    }

    void stopServer() {
        running = false;
        DatagramSocket current = socket;
        if (current != null) current.close();
    }
}
