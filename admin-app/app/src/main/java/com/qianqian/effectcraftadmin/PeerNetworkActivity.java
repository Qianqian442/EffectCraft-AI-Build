package com.qianqian.effectcraftadmin;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** User-controlled view for starting this phone as a local EffectCraft peer node. */
public final class PeerNetworkActivity extends Activity {
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private LinearLayout content;
    private TextView localStatus;
    private LinearLayout peerRows;

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private TextView label(String value, int size, boolean bold) {
        TextView v = new TextView(this);
        v.setText(value);
        v.setTextSize(size);
        v.setTextColor(Color.rgb(32, 38, 48));
        if (bold) v.setTypeface(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD);
        v.setGravity(Gravity.CENTER_VERTICAL);
        return v;
    }

    private Button button(String value) {
        Button b = new Button(this);
        b.setText(value);
        b.setAllCaps(false);
        return b;
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(245, 247, 250));
        getWindow().setNavigationBarColor(Color.rgb(245, 247, 250));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        buildPage();
        refreshPage();
    }

    private void buildPage() {
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(18), dp(16), dp(18), dp(16));
        content.setBackgroundColor(Color.rgb(245, 247, 250));

        content.addView(label("EffectCraft 手机节点网络", 22, true),
            new LinearLayout.LayoutParams(-1, dp(52)));
        content.addView(label("让这部手机成为一个可被附近 EffectCraft 节点发现的账号节点。", 14, false));

        localStatus = label("", 13, false);
        localStatus.setPadding(dp(12), dp(10), dp(12), dp(10));
        localStatus.setBackgroundColor(Color.WHITE);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(-1, dp(100));
        statusParams.topMargin = dp(12);
        content.addView(localStatus, statusParams);

        Button start = button("启动本机节点");
        content.addView(start, new LinearLayout.LayoutParams(-1, dp(48)));
        start.setOnClickListener(v -> startNode());

        Button stop = button("停止本机节点");
        content.addView(stop, new LinearLayout.LayoutParams(-1, dp(48)));
        stop.setOnClickListener(v -> {
            stopService(new Intent(this, LanServerService.class));
            Toast.makeText(this, "已请求停止本机节点", Toast.LENGTH_SHORT).show();
            refreshPage();
        });

        Button refresh = button("刷新附近节点");
        content.addView(refresh, new LinearLayout.LayoutParams(-1, dp(48)));
        refresh.setOnClickListener(v -> refreshPage());

        content.addView(label("发现的附近节点", 17, true),
            new LinearLayout.LayoutParams(-1, dp(42)));
        ScrollView scroll = new ScrollView(this);
        peerRows = new LinearLayout(this);
        peerRows.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(peerRows);
        content.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));

        Button back = button("返回");
        content.addView(back, new LinearLayout.LayoutParams(-1, dp(46)));
        back.setOnClickListener(v -> finish());

        TextView note = label("当前版本只完成同一 Wi-Fi 内的节点广播与发现，不会自动复制账号数据；跨 Wi-Fi 直连、NAT 穿透、节点信任和签名同步仍在后续开发。", 11, false);
        note.setTextColor(Color.rgb(100, 106, 116));
        LinearLayout.LayoutParams noteParams = new LinearLayout.LayoutParams(-1, -2);
        noteParams.topMargin = dp(10);
        content.addView(note, noteParams);

        setContentView(content);
    }

    private void startNode() {
        Intent intent = new Intent(this, LanServerService.class);
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent);
            else startService(intent);
            getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE)
                .edit().putBoolean("node_requested", true).apply();
            Toast.makeText(this, "已启动节点服务；请保持应用允许后台运行", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "启动失败：" + e.getMessage(), Toast.LENGTH_LONG).show();
        }
        refreshPage();
    }

    private void refreshPage() {
        SharedPreferences prefs = getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE);
        boolean running = prefs.getBoolean("node_running", false);
        String ip = LanAccountServer.getWifiIpv4();
        String node = LanPeerDiscovery.getNodeId(this);
        String address = ip.isEmpty() ? "未连接 Wi-Fi" : ip + ":" + LanPeerDiscovery.PORT;
        localStatus.setText(
            "节点状态：" + (running ? "运行中" : "未启动") +
            "\n本机地址：" + address +
            "\n节点编号：" + node.substring(0, Math.min(18, node.length()))
        );
        peerRows.removeAllViews();
        JSONArray peers = LanPeerDiscovery.getSavedPeers(this);
        if (peers.length() == 0) {
            TextView empty = label("暂未发现其他节点。请让另一部手机连接同一个 Wi-Fi，并启动它的 EffectCraft 手机节点。", 13, false);
            empty.setPadding(dp(8), dp(12), dp(8), dp(12));
            peerRows.addView(empty);
            return;
        }
        for (int i = 0; i < peers.length(); i++) {
            JSONObject peer = peers.optJSONObject(i);
            if (peer == null) continue;
            String peerId = peer.optString("node_id", "未知节点");
            String peerName = peer.optString("service", "EffectCraft 节点");
            String peerAddress = peer.optString("address", "") + ":" + peer.optInt("port", LanPeerDiscovery.PORT);
            LinearLayout card = new LinearLayout(this);
            card.setOrientation(LinearLayout.VERTICAL);
            card.setPadding(dp(10), dp(8), dp(10), dp(8));
            card.setBackgroundColor(Color.WHITE);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
            params.bottomMargin = dp(8);
            peerRows.addView(card, params);
            card.addView(label(peerName, 15, true));
            card.addView(label("地址：" + peerAddress, 12, false));
            card.addView(label("节点编号：" + peerId, 11, false));
            Button copy = button("复制节点地址");
            card.addView(copy);
            copy.setOnClickListener(v -> {
                ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                if (clipboard != null) {
                    clipboard.setPrimaryClip(ClipData.newPlainText("EffectCraft peer", peerAddress));
                    Toast.makeText(this, "节点地址已复制", Toast.LENGTH_SHORT).show();
                }
            });
            Button test = button("测试节点是否可访问");
            card.addView(test);
            test.setOnClickListener(v -> testPeer(peerAddress, test));
        }
    }

    private void testPeer(String address, Button button) {
        button.setEnabled(false);
        button.setText("正在测试…");
        io.execute(() -> {
            String result;
            Socket socket = null;
            try {
                int split = address.lastIndexOf(':');
                if (split <= 0) throw new IllegalArgumentException("节点地址格式不正确");
                String host = address.substring(0, split);
                int port = Integer.parseInt(address.substring(split + 1));
                socket = new Socket();
                socket.connect(new InetSocketAddress(host, port), 3000);
                socket.setSoTimeout(3000);
                OutputStream out = socket.getOutputStream();
                out.write(("GET /health HTTP/1.1\r\nHost: " + address + "\r\nConnection: close\r\n\r\n").getBytes(java.nio.charset.StandardCharsets.US_ASCII));
                out.flush();
                ByteArrayOutputStream response = new ByteArrayOutputStream();
                byte[] buffer = new byte[1024];
                int count;
                while ((count = socket.getInputStream().read(buffer)) != -1) {
                    response.write(buffer, 0, count);
                    if (response.size() > 8192) break;
                }
                String firstLine = response.toString("UTF-8").split("\\r?\\n", 2)[0];
                result = firstLine.contains(" 200 ") ? "节点可访问" : "节点响应：" + firstLine;
            } catch (Exception e) {
                result = "暂时无法连接：" + e.getMessage();
            } finally {
                if (socket != null) try { socket.close(); } catch (Exception ignored) { }
            }
            final String message = result;
            runOnUiThread(() -> {
                button.setEnabled(true);
                button.setText("测试节点是否可访问");
                Toast.makeText(this, message, Toast.LENGTH_LONG).show();
            });
        });
    }

    @Override protected void onDestroy() {
        io.shutdownNow();
        super.onDestroy();
    }
}
