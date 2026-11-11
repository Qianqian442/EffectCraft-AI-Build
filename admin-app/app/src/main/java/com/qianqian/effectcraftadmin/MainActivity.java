package com.qianqian.effectcraftadmin;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.app.AlertDialog;
import android.app.DatePickerDialog;
import android.app.TimePickerDialog;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Calendar;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private static final String DEFAULT_SERVER = BuildConfig.ACCOUNT_API_URL;
    private String server = DEFAULT_SERVER;
    private String adminToken = "";
    private LinearLayout root;
    private LinearLayout rows;
    private EditText serverInput;
    private EditText usernameInput;
    private EditText passwordInput;
    private EditText searchInput;
    private Button loginButton;
    private TextView loginStatus;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(245, 247, 250));
        getWindow().setNavigationBarColor(Color.rgb(245, 247, 250));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        String savedServer = getPreferences(MODE_PRIVATE).getString("server", "");
        server = savedServer.startsWith("https://") ? trimServer(savedServer) : trimServer(DEFAULT_SERVER);
        adminToken = savedServer.startsWith("https://")
            ? getPreferences(MODE_PRIVATE).getString("admin_token", "") : "";
        if (!adminToken.isEmpty()) {
            showConnecting("正在连接云端账号服务并恢复管理员登录…");
            loadUsers("");
        } else {
            showLogin();
        }
    }

    /** Server-authoritative global node switch; never trust a local preference for this control. */

    /** Independent local account-server switch; does not control the P2P network switch below. */
    private void addAccountServerPanel(LinearLayout page) {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), dp(10), dp(12), dp(10));
        panel.setBackground(rounded(Color.WHITE));
        panel.addView(text("管理员手机账号服务器", 16, true));
        TextView status = text("", 13, false);
        panel.addView(status);
        Button toggle = button("读取状态…");
        panel.addView(toggle, new LinearLayout.LayoutParams(-1, dp(46)));
        TextView note = text("此阶段服务仅监听本机 Wi-Fi，尚未完成跨网络 TLS/安全中继和主 APK 客户端接入。请勿在不可信 Wi-Fi 上传输真实账号密码。", 11, false);
        note.setTextColor(Color.rgb(160, 85, 35));
        panel.addView(note);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = dp(10);
        page.addView(panel, params);
        refreshAccountServerPanel(status, toggle);
        toggle.setOnClickListener(v -> {
            boolean running = getSharedPreferences("effectcraft_account_server_state", MODE_PRIVATE)
                .getBoolean("requested", false);
            Intent intent = new Intent(this, AccountServerService.class);
            try {
                if (running) {
                    stopService(intent);
                    getSharedPreferences("effectcraft_account_server_state", MODE_PRIVATE)
                        .edit().putBoolean("requested", false).apply();
                } else {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent);
                    else startService(intent);
                    getSharedPreferences("effectcraft_account_server_state", MODE_PRIVATE)
                        .edit().putBoolean("requested", true).apply();
                }
            } catch (Exception e) {
                toast("账号服务器操作失败：" + e.getMessage());
            }
            status.postDelayed(() -> refreshAccountServerPanel(status, toggle), 700);
        });
    }

    private void refreshAccountServerPanel(TextView status, Button toggle) {
        boolean requested = getSharedPreferences("effectcraft_account_server_state", MODE_PRIVATE)
            .getBoolean("requested", false);
        boolean process = getSharedPreferences("effectcraft_account_server_state", MODE_PRIVATE)
            .getBoolean("service_process", false);
        String ip = LanAccountServer.getWifiIpv4();
        String bound = requested && process && !ip.isEmpty() ? ip + ":" + LanAccountServer.PORT : "尚未监听";
        status.setText("服务开关：" + (requested ? "开启" : "关闭") +
            " · 服务进程：" + (process ? "运行中" : "未运行") +
            "\n本机监听地址：" + bound +
            "\n跨地区可达性：尚未验证");
        toggle.setText(requested ? "关闭账号服务器" : "开启账号服务器");
    }

    private void addGlobalNodePanel(LinearLayout page) {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), dp(10), dp(12), dp(10));
        panel.setBackground(rounded(Color.WHITE));
        panel.addView(text("全局节点网络控制", 16, true));
        TextView status = text("正在读取云端节点网络状态…", 13, false);
        panel.addView(status);
        TextView count = text("在线节点：读取中", 12, false);
        panel.addView(count);
        Button toggle = button("读取中…");
        toggle.setEnabled(false);
        panel.addView(toggle, new LinearLayout.LayoutParams(-1, dp(46)));
        TextView note = text("关闭后由云端拒绝新的节点会话并断开现有会话；开启后允许节点重新连接。", 11, false);
        note.setTextColor(Color.rgb(95, 103, 115));
        panel.addView(note);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = dp(10);
        page.addView(panel, params);

        final boolean[] enabled = new boolean[]{true};
        requestAsync("GET", "/v1/admin/network", null, true, result -> {
            if (result == null) {
                status.setText("云端总开关暂不可用：请先部署最新账号服务");
                toggle.setText("重新读取状态");
                toggle.setEnabled(true);
                toggle.setOnClickListener(v -> addGlobalNodePanel((LinearLayout) panel.getParent()));
                return;
            }
            JSONObject network = result.optJSONObject("network");
            if (network == null) {
                status.setText("云端返回的节点状态格式不正确");
                return;
            }
            enabled[0] = network.optBoolean("enabled", false);
            status.setText(enabled[0] ? "状态：已开启 · 允许跨地区节点连接" : "状态：已关闭 · 节点连接已被云端阻止");
            toggle.setText(enabled[0] ? "关闭全部服务器节点" : "开启全部服务器节点");
            toggle.setEnabled(true);
            requestAsync("GET", "/v1/admin/network/nodes", null, true, nodesResult -> {
                if (nodesResult != null) {
                    JSONArray nodes = nodesResult.optJSONArray("nodes");
                    count.setText("在线节点会话：" + (nodes == null ? 0 : nodes.length()));
                } else {
                    count.setText("在线节点会话：暂时无法读取");
                }
            });
            toggle.setOnClickListener(v -> {
                boolean next = !enabled[0];
                toggle.setEnabled(false);
                toggle.setText(next ? "正在开启…" : "正在关闭…");
                JSONObject body = new JSONObject();
                try { body.put("enabled", next); } catch (Exception ignored) {}
                requestAsync("POST", "/v1/admin/network", body, true, changed -> {
                    if (changed == null) {
                        toggle.setEnabled(true);
                        toggle.setText(enabled[0] ? "关闭全部服务器节点" : "开启全部服务器节点");
                        status.setText("操作未确认；云端状态可能未改变，请重新读取");
                        return;
                    }
                    JSONObject updated = changed.optJSONObject("network");
                    if (updated == null) {
                        toggle.setEnabled(true);
                        status.setText("服务器返回状态异常，请重新读取");
                        return;
                    }
                    enabled[0] = updated.optBoolean("enabled", false);
                    status.setText(enabled[0] ? "状态：已开启 · 允许节点重新连接" : "状态：已关闭 · 云端已阻止节点会话");
                    toggle.setText(enabled[0] ? "关闭全部服务器节点" : "开启全部服务器节点");
                    toggle.setEnabled(true);
                    count.setText(enabled[0] ? "节点正在尝试重新连接" : "在线节点会话已要求断开");
                    // Also control this admin phone's own P2P worker service.
                    Intent nodeIntent = new Intent(MainActivity.this, LanServerService.class);
                    try {
                        if (enabled[0]) {
                            getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE)
                                .edit().putBoolean("node_enabled", true).apply();
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(nodeIntent);
                            else startService(nodeIntent);
                        } else {
                            getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE)
                                .edit().putBoolean("node_enabled", false).apply();
                            stopService(nodeIntent);
                        }
                    } catch (Exception serviceError) {
                        status.setText(status.getText() + "；本机节点服务启动/停止异常：" + serviceError.getMessage());
                    }
                    toast(enabled[0] ? "已开启 P2P 总开关并启动本机节点" : "已关闭 P2P 总开关并停止本机节点");
                });
            });
        });
    }

    private int dp(float value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private TextView text(String value, int size, boolean bold) {
        TextView v = new TextView(this);
        v.setText(value);
        v.setTextSize(size);
        v.setTextColor(Color.rgb(30, 35, 45));
        if (bold) v.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        v.setGravity(Gravity.CENTER_VERTICAL);
        return v;
    }

    private GradientDrawable rounded(int color) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(12));
        return d;
    }

    private LinearLayout column() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setPadding(dp(18), dp(18), dp(18), dp(18));
        l.setBackgroundColor(Color.rgb(245, 247, 250));
        return l;
    }

    private EditText field(String hint, boolean password) {
        EditText e = new EditText(this);
        e.setSingleLine(true);
        e.setTextSize(15);
        e.setHint(hint);
        e.setPadding(dp(13), 0, dp(13), 0);
        e.setBackground(rounded(Color.WHITE));
        e.setInputType(password ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD : InputType.TYPE_CLASS_TEXT);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(50));
        p.bottomMargin = dp(10);
        return e;
    }

    private Button button(String label) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextSize(14);
        return b;
    }

    private void setRoot(LinearLayout content) {
        root = content;
        setContentView(root);
    }

    private void showConnecting(String message) {
        LinearLayout page = column();
        page.addView(text("Ae账号管理", 24, true), new LinearLayout.LayoutParams(-1, dp(56)));
        TextView status = text(message, 15, false);
        page.addView(status, new LinearLayout.LayoutParams(-1, dp(64)));
        page.addView(text("正在通过 HTTPS 连接云端账号服务；不需要其他用户与管理设备处于同一 Wi-Fi。", 12, false));
        Button retry = button("重新连接");
        retry.setOnClickListener(v -> {
            showConnecting("正在重新连接云端账号服务…");
            loadUsers("");
        });
        page.addView(retry, new LinearLayout.LayoutParams(-1, dp(48)));
        Button logout = button("返回管理员登录");
        logout.setOnClickListener(v -> {
            adminToken = "";
            getPreferences(MODE_PRIVATE).edit().remove("admin_token").apply();
            showLogin();
        });
        page.addView(logout, new LinearLayout.LayoutParams(-1, dp(48)));
        setRoot(page);
    }

    private void showLogin() {
        LinearLayout page = column();
        TextView title = text("EffectCraft 账号管理", 24, true);
        page.addView(title, new LinearLayout.LayoutParams(-1, dp(56)));
        page.addView(text("云端账号管理：不同地区、不同网络的用户可以注册和登录。", 14, false));
        page.addView(text("管理设备只需能访问 Cloudflare HTTPS 服务，不需要保持开机供其他用户连接。", 13, false));
        page.addView(text("主 APK 用户端自动加入节点网络；本管理版只负责账号管理、封禁解禁和全局节点开关。", 13, false));
        page.addView(text("服务器地址", 13, true));
        serverInput = field("服务器地址由管理版自动配置", false);
        serverInput.setText(server);
        page.addView(serverInput);
        page.addView(text("管理员账号", 13, true));
        usernameInput = field("admin", false);
        usernameInput.setText("admin");
        page.addView(usernameInput);
        page.addView(text("管理员密码", 13, true));
        passwordInput = field("输入云端管理员密码", true);
        page.addView(passwordInput);
        loginButton = button("登录管理后台");
        page.addView(loginButton, new LinearLayout.LayoutParams(-1, dp(52)));
        loginStatus = text("请输入云端 Worker HTTPS 地址和管理员密码", 12, false);
        loginStatus.setTextColor(Color.rgb(95, 103, 115));
        page.addView(loginStatus, new LinearLayout.LayoutParams(-1, dp(36)));
        loginButton.setOnClickListener(v -> doAdminLogin());
        page.addView(text("管理员账号固定为 admin。管理员密码由云端 Worker 的 ADMIN_PASSWORD 密钥设置。", 12, false));
        setRoot(page);
    }

    private void doAdminLogin() {
        server = trimServer(serverInput.getText().toString());
        String user = usernameInput.getText().toString().trim();
        // The generated admin password contains no spaces. Ignore accidental
        // leading/trailing whitespace added by mobile clipboard or IME input.
        String pass = passwordInput.getText().toString().trim();
        if (server.isEmpty() || user.isEmpty() || pass.isEmpty()) {
            toast("请填写服务器地址、管理员账号和密码");
            return;
        }
        JSONObject body = new JSONObject();
        try { body.put("username", user); body.put("password", pass); } catch (Exception ignored) {}
        if (loginButton != null) {
            loginButton.setEnabled(false);
            loginButton.setText("正在验证…");
        }
        if (loginStatus != null) loginStatus.setText("正在连接云端 HTTPS 服务并验证管理员密码…");
        requestAsync("POST", "/v1/admin/login", body, false, result -> {
            if (result == null) {
                if (loginButton != null) {
                    loginButton.setEnabled(true);
                    loginButton.setText("登录管理后台");
                }
                if (loginStatus != null) loginStatus.setText("登录未完成，请检查 HTTPS 服务器地址、网络和密码后重试。");
                return;
            }
            try {
                adminToken = result.getString("token");
                getPreferences(MODE_PRIVATE).edit().putString("server", server).putString("admin_token", adminToken).apply();
                showConnecting("密码验证成功，正在读取账号列表…");
                loadUsers("");
            } catch (Exception e) {
                toast("管理员登录返回数据不正确");
                if (loginButton != null) {
                    loginButton.setEnabled(true);
                    loginButton.setText("登录管理后台");
                }
                if (loginStatus != null) loginStatus.setText("登录返回内容异常，请重试。");
            }
        });
    }

    private String trimServer(String value) {
        String s = value.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }

    private interface JsonCallback { void done(JSONObject result); }

    private void requestAsync(String method, String path, JSONObject body, boolean auth, JsonCallback callback) {
        io.execute(() -> {
            JSONObject result = null;
            String error = null;
            HttpURLConnection c = null;
            try {
                URL url = new URL(server + path);
                if (!"https".equalsIgnoreCase(url.getProtocol()) ||
                    url.getHost() == null || !url.getHost().endsWith(".workers.dev")) {
                    throw new java.io.IOException("请填写完整的 HTTPS workers.dev 地址");
                }
                c = (HttpURLConnection) url.openConnection();
                c.setRequestMethod(method);
                c.setConnectTimeout(8000);
                c.setReadTimeout(10000);
                c.setRequestProperty("Accept", "application/json");
                if (auth && !adminToken.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + adminToken);
                if (body != null) {
                    c.setDoOutput(true);
                    c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                    byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                    try (OutputStream out = c.getOutputStream()) { out.write(bytes); }
                }
                int code = c.getResponseCode();
                InputStream in = code >= 200 && code < 300 ? c.getInputStream() : c.getErrorStream();
                ByteArrayOutputStream data = new ByteArrayOutputStream();
                if (in != null) {
                    try (InputStream stream = in) {
                        byte[] buffer = new byte[4096];
                        int n;
                        while ((n = stream.read(buffer)) > 0) data.write(buffer, 0, n);
                    }
                }
                JSONObject parsed = new JSONObject(new String(data.toByteArray(), StandardCharsets.UTF_8));
                if (code >= 200 && code < 300) result = parsed;
                else {
                    Object detail = parsed.opt("detail");
                    if (detail instanceof JSONObject) error = ((JSONObject) detail).optString("message", detail.toString());
                    else error = detail == null ? ("HTTP " + code) : detail.toString();
                    if ((code == 401 || code == 403) && auth) {
                        adminToken = "";
                        error = "管理员登录已失效：" + error;
                        getPreferences(MODE_PRIVATE).edit().remove("admin_token").apply();
                    }
                }
            } catch (Exception e) {
                error = "无法连接服务器：" + e.getMessage();
            } finally {
                if (c != null) c.disconnect();
            }
            JSONObject finalResult = result;
            String finalError = error;
            runOnUiThread(() -> {
                if (finalError != null) {
                    toast(finalError);
                    if (finalError.contains("401") || finalError.contains("管理员")) showLogin();
                }
                if (callback != null) callback.done(finalResult);
            });
        });
    }

    private void loadUsers(String query) {
        String encoded;
        try { encoded = URLEncoder.encode(query, "UTF-8"); } catch (Exception e) { encoded = ""; }
        requestAsync("GET", "/v1/admin/users?q=" + encoded, null, true, result -> {
            if (result == null) {
                // Do not leave the Activity blank or stuck on an expired token.
                adminToken = "";
                getPreferences(MODE_PRIVATE).edit().remove("admin_token").apply();
                showLogin();
                return;
            }
            showUsers(result.optJSONArray("users"));
        });
    }

    private void showUsers(JSONArray users) {
        LinearLayout page = column();
        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = text("账号管理", 22, true);
        top.addView(title, new LinearLayout.LayoutParams(0, dp(48), 1));
        Button refresh = button("刷新");
        top.addView(refresh);
        refresh.setOnClickListener(v -> loadUsers(searchInput == null ? "" : searchInput.getText().toString()));
        page.addView(top);
        addAccountServerPanel(page);
        addGlobalNodePanel(page);
        searchInput = field("搜索 QQ号 / 微信号 / 名字", false);
        page.addView(searchInput);
        Button search = button("搜索账号");
        page.addView(search, new LinearLayout.LayoutParams(-1, dp(46)));
        search.setOnClickListener(v -> loadUsers(searchInput.getText().toString()));
        ScrollView scroll = new ScrollView(this);
        rows = new LinearLayout(this);
        rows.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(rows);
        LinearLayout.LayoutParams scrollParams = new LinearLayout.LayoutParams(-1, 0, 1);
        scrollParams.topMargin = dp(12);
        page.addView(scroll, scrollParams);
        Button logout = button("退出管理员账号");
        page.addView(logout, new LinearLayout.LayoutParams(-1, dp(46)));
        logout.setOnClickListener(v -> {
            adminToken = "";
            getPreferences(MODE_PRIVATE).edit().remove("admin_token").apply();
            showLogin();
        });
        setRoot(page);
        if (users == null) return;
        for (int i = 0; i < users.length(); i++) {
            JSONObject user = users.optJSONObject(i);
            if (user == null) continue;
            addUserRow(user);
        }
        page.invalidate();
    }

    private void updateVisibleUser(JSONObject user) {
        if (user == null || rows == null) return;
        String id = user.optString("id");
        for (int i = 0; i < rows.getChildCount(); i++) {
            View child = rows.getChildAt(i);
            if (id.equals(child.getTag())) {
                rows.removeViewAt(i);
                break;
            }
        }
        addUserRow(user);
    }

    private void addUserRow(JSONObject user) {
        String id = user.optString("id");
        String name = user.optString("name", "未命名");
        String qq = user.optString("qq", "");
        String wechat = user.optString("wechat", "");
        String until = user.optString("banned_until", "");
        boolean banned = !until.isEmpty() && !until.equals("null");
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(10), dp(9), dp(8), dp(9));
        row.setBackground(rounded(Color.WHITE));
        row.setTag(id);
        LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT);
        rp.bottomMargin = dp(8);
        rows.addView(row, rp);

        String avatarUrl = user.optString("avatar_url", "");
        if (!avatarUrl.isEmpty()) {
            ImageView avatar = new ImageView(this);
            avatar.setScaleType(ImageView.ScaleType.CENTER_CROP);
            avatar.setBackground(rounded(Color.rgb(66, 105, 180)));
            avatar.setClipToOutline(true);
            row.addView(avatar, new LinearLayout.LayoutParams(dp(46), dp(46)));
            loadAvatar(avatar, avatarUrl);
        } else {
            TextView avatar = text(name.isEmpty() ? "?" : name.substring(0, 1), 20, true);
            avatar.setGravity(Gravity.CENTER);
            avatar.setTextColor(Color.WHITE);
            avatar.setBackground(rounded(Color.rgb(66, 105, 180)));
            row.addView(avatar, new LinearLayout.LayoutParams(dp(46), dp(46)));
        }

        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(dp(10), 0, dp(6), 0);
        TextView label = text(name, 15, true);
        TextView ids = text("QQ " + qq + "  ·  微信 " + wechat, 11, false);
        ids.setTextColor(Color.rgb(95, 103, 115));
        info.addView(label);
        info.addView(ids);
        if (banned) {
            TextView ban = text("封禁至 " + until, 10, true);
            ban.setTextColor(Color.rgb(180, 58, 58));
            info.addView(ban);
        }
        row.addView(info, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));

        // Keep both actions visible for every account. Reapplying a ban is allowed
        // so the administrator can extend or change its expiry; unban is disabled
        // only when the account is not currently banned.
        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.CENTER_VERTICAL);

        Button banButton = button("封禁");
        Button unbanButton = button("解禁");
        unbanButton.setEnabled(banned);

        LinearLayout.LayoutParams actionParams = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, dp(42)
        );
        actionParams.leftMargin = dp(3);
        actionParams.rightMargin = dp(3);
        actions.addView(banButton, actionParams);
        actions.addView(unbanButton, actionParams);
        row.addView(actions, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        row.setOnClickListener(v -> showUserDetails(user));
        banButton.setOnClickListener(v -> chooseBan(id));
        unbanButton.setOnClickListener(v -> unban(id));
    }

    private void loadAvatar(ImageView view, String uri) {
        io.execute(() -> {
            HttpURLConnection c = null;
            try {
                c = (HttpURLConnection) new URL(uri).openConnection();
                c.setConnectTimeout(5000);
                c.setReadTimeout(5000);
                c.setInstanceFollowRedirects(true);
                try (InputStream in = c.getInputStream()) {
                    Bitmap bitmap = BitmapFactory.decodeStream(in);
                    if (bitmap != null) runOnUiThread(() -> view.setImageBitmap(bitmap));
                }
            } catch (Exception ignored) {
                // Keep the colored placeholder when the optional avatar cannot be loaded.
            } finally {
                if (c != null) c.disconnect();
            }
        });
    }

    private void showUserDetails(JSONObject user) {
        String message = "名字：" + user.optString("name") +
                "\nQQ号：" + user.optString("qq") +
                "\n微信号：" + user.optString("wechat") +
                "\n注册时间：" + user.optString("created_at") +
                "\n头像地址：" + user.optString("avatar_url") +
                "\n封禁截止：" + user.optString("banned_until") +
                "\n封禁原因：" + user.optString("ban_reason");
        new AlertDialog.Builder(this).setTitle("账号个人信息")
                .setMessage(message)
                .setPositiveButton("OK", null).show();
    }

    private void chooseBan(String id) {
        Calendar selected = Calendar.getInstance();
        new DatePickerDialog(this, (view, year, month, day) -> {
            selected.set(Calendar.YEAR, year);
            selected.set(Calendar.MONTH, month);
            selected.set(Calendar.DAY_OF_MONTH, day);
            new TimePickerDialog(this, (timeView, hour, minute) -> {
                selected.set(Calendar.HOUR_OF_DAY, hour);
                selected.set(Calendar.MINUTE, minute);
                selected.set(Calendar.SECOND, 0);
                selected.set(Calendar.MILLISECOND, 0);
                askBanReason(id, selected);
            }, selected.get(Calendar.HOUR_OF_DAY), selected.get(Calendar.MINUTE), true).show();
        }, selected.get(Calendar.YEAR), selected.get(Calendar.MONTH), selected.get(Calendar.DAY_OF_MONTH)).show();
    }

    private void askBanReason(String id, Calendar until) {
        EditText reason = new EditText(this);
        reason.setHint("填写封禁原因（必填）");
        reason.setMinLines(2);
        reason.setGravity(Gravity.TOP);
        new AlertDialog.Builder(this).setTitle("确认封禁")
                .setMessage("封禁截止：" + until.getTime())
                .setView(reason)
                .setNegativeButton("取消", null)
                .setPositiveButton("确认封禁", (dialog, which) -> {
                    String why = reason.getText().toString().trim();
                    if (why.isEmpty()) { toast("请填写封禁原因"); return; }
                    JSONObject body = new JSONObject();
                    try {
                        body.put("banned_until", Instant.ofEpochMilli(until.getTimeInMillis()).toString());
                        body.put("reason", why);
                    } catch (Exception ignored) {}
                    requestAsync("POST", "/v1/admin/users/" + id + "/ban", body, true, result -> {
                        if (result != null) {
                            int delivered = result.optInt("notification_delivered", 0);
                            toast(delivered > 0
                                ? "已封禁，并已通知在线 Ae 设备（" + delivered + " 个连接）"
                                : "封禁记录已保存；未发现在线 Ae 连接，对方下次联网或打开 Ae 时核验");
                            updateVisibleUser(result.optJSONObject("user"));
                        }
                    });
                }).show();
    }

    private void unban(String id) {
        new AlertDialog.Builder(this).setTitle("取消封禁")
                .setMessage("确定取消该账号的封禁吗？在线用户收到通知并验证后即可恢复；离线用户下次打开 Ae 时恢复。")
                .setNegativeButton("取消", null)
                .setPositiveButton("确认取消封禁", (dialog, which) -> {
                    JSONObject body = new JSONObject();
                    try { body.put("banned_until", JSONObject.NULL); body.put("reason", ""); } catch (Exception ignored) {}
                    requestAsync("POST", "/v1/admin/users/" + id + "/ban", body, true, result -> {
                        if (result != null) {
                            int delivered = result.optInt("notification_delivered", 0);
                            toast(delivered > 0
                                ? "已解禁，并已通知在线 Ae 设备（" + delivered + " 个连接）"
                                : "解禁记录已保存；对方下次联网或打开 Ae 时核验");
                            updateVisibleUser(result.optJSONObject("user"));
                        }
                    });
                }).show();
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
    }

    @Override protected void onDestroy() {
        super.onDestroy();
        io.shutdownNow();
    }
}
