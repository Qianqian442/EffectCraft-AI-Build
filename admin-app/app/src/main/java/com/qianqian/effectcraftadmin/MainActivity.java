package com.qianqian.effectcraftadmin;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DatePickerDialog;
import android.app.TimePickerDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
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
    private volatile String server = DEFAULT_SERVER;
    private String adminToken = "";
    private LinearLayout root;
    private LinearLayout rows;
    private EditText serverInput;
    private EditText usernameInput;
    private EditText passwordInput;
    private EditText searchInput;
    private Button loginButton;
    private TextView loginStatus;
    private TextView p2pStatusView;
    private TextView accountCountView;
    private TextView accountFilterCountView;
    private Switch accountServiceSwitch;
    private String serviceStartError = "";
    private boolean serverToggleChanging = false;
    private boolean accountServiceSwitchChanging = false;
    private final Handler p2pUiHandler = new Handler(Looper.getMainLooper());
    private final Runnable p2pStatusRefresh = new Runnable() {
        @Override public void run() {
            if (p2pStatusView != null) p2pStatusView.setText(readP2PStatus());
            p2pUiHandler.postDelayed(this, 5000);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        // The Cloudflare HTTPS API is the single account authority; do not start a second local account database.
        p2pUiHandler.postDelayed(p2pStatusRefresh, 2500);
        getWindow().setStatusBarColor(Color.rgb(245, 247, 250));
        getWindow().setNavigationBarColor(Color.rgb(245, 247, 250));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        java.util.ArrayList<String> availableServers = cloudServerPool();
        server = availableServers.isEmpty() ? trimServer(DEFAULT_SERVER) : availableServers.get(0);
        String savedServer = getPreferences(MODE_PRIVATE).getString("server", "");
        if (availableServers.contains(savedServer)) server = savedServer;
        else if (!savedServer.isEmpty()) getPreferences(MODE_PRIVATE).edit().remove("admin_token").remove("server").apply();
        adminToken = getPreferences(MODE_PRIVATE).getString("admin_token", "");
        if (!adminToken.isEmpty()) {
            showConnecting("正在验证云端管理员账号…");
            loadUsers("");
        } else {
            showLogin();
        }
    }

    private java.util.ArrayList<String> cloudServerPool() {
        java.util.LinkedHashSet<String> values = new java.util.LinkedHashSet<>();
        String configured = BuildConfig.ACCOUNT_API_URLS == null ? "" : BuildConfig.ACCOUNT_API_URLS;
        for (String item : configured.split(";")) {
            String endpoint = trimServer(item);
            if (endpoint.startsWith("https://") && !endpoint.contains("@")) values.add(endpoint);
        }
        String primary = trimServer(BuildConfig.ACCOUNT_API_URL == null ? "" : BuildConfig.ACCOUNT_API_URL);
        if (primary.startsWith("https://")) values.add(primary);
        return new java.util.ArrayList<>(values);
    }

    private void switchCloudServer() {
        java.util.ArrayList<String> endpoints = cloudServerPool();
        if (endpoints.size() < 2) {
            toast("目前只配置了一个云端入口；备用 HTTPS 入口尚未部署");
            return;
        }
        int current = endpoints.indexOf(server);
        server = endpoints.get((current < 0 ? 0 : current + 1) % endpoints.size());
        getPreferences(MODE_PRIVATE).edit().putString("server", server).apply();
        toast("已切换云端入口：" + server);
        if (!adminToken.isEmpty()) loadUsers("");
        else showLogin();
    }

    private String readP2PStatus() {
        if (!NativeP2P.isAvailable()) return "原生 P2P 组件未加载，请检查管理版 APK 构建包。";
        try {
            JSONObject value = new JSONObject(NativeP2P.status());
            String peer = value.optString("peerId", "等待分配");
            String state = value.optString("status", "starting");
            int peers = value.optInt("discoveredPeers", 0);
            int candidates = value.optInt("relayCandidates", 0);
            int active = value.optInt("activeRelays", 0);
            int direct = value.optInt("directPeers", 0);
            String error = value.optString("lastError", "");
            return "节点 ID：" + peer
                + "\n网络状态：" + state
                + " · 已发现节点：" + peers
                + " · 候选中继：" + candidates
                + " · 已获准中继：" + active
                + " · 直连节点：" + direct
                + (error.isEmpty() ? "" : "\n最近错误：" + error);
        } catch (Exception error) {
            return "正在读取本机 P2P 状态：" + error.getMessage();
        }
    }

    private boolean isNodeServerEnabled() {
        return getSharedPreferences(LanServerService.SETTINGS_PREFS, MODE_PRIVATE)
            .getBoolean("node_server_enabled", true);
    }

    private void startNodeServerService() {
        Intent authorityService = new Intent(this, LanServerService.class);
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(authorityService);
            else startService(authorityService);
            serviceStartError = "";
        } catch (RuntimeException error) {
            serviceStartError = "后台账号服务启动失败：" + error.getClass().getSimpleName()
                + (error.getMessage() == null ? "" : " · " + error.getMessage());
            throw error;
        }
    }

    private void setNodeServerEnabled(boolean enabled, Switch control) {
        if (serverToggleChanging) return;
        boolean previous = isNodeServerEnabled();
        try {
            getSharedPreferences(LanServerService.SETTINGS_PREFS, MODE_PRIVATE)
                .edit().putBoolean("node_server_enabled", enabled).apply();
            if (enabled) {
                startNodeServerService();
                toast("账号服务器已开启，正在启动 P2P 节点");
            } else {
                stopService(new Intent(this, LanServerService.class));
                toast("账号服务器已关闭，其他手机暂时不能注册或登录");
            }
            if (p2pStatusView != null) p2pStatusView.setText(readP2PStatus());
        } catch (RuntimeException error) {
            getSharedPreferences(LanServerService.SETTINGS_PREFS, MODE_PRIVATE)
                .edit().putBoolean("node_server_enabled", previous).apply();
            serverToggleChanging = true;
            control.setChecked(previous);
            serverToggleChanging = false;
            toast("切换服务器失败：" + (error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage()));
        }
    }

    private void addNodeServerToggle(LinearLayout parent) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        TextView label = text("本机 P2P 辅助节点开关", 14, true);
        row.addView(label, new LinearLayout.LayoutParams(0, dp(48), 1));
        Switch control = new Switch(this);
        control.setTextOn("开启");
        control.setTextOff("关闭");
        control.setChecked(isNodeServerEnabled());
        control.setOnCheckedChangeListener((button, enabled) -> setNodeServerEnabled(enabled, control));
        row.addView(control, new LinearLayout.LayoutParams(-2, dp(48)));
        parent.addView(row);
        parent.addView(text("仅控制本机 P2P 辅助节点；主 APK 与管理版的账号数据统一保存在 Cloudflare 云端，不受此开关影响。", 11, false));
    }

    /** The administrator phone is the account authority; P2P carries authenticated account RPC. */
    private void addGlobalNodePanel(LinearLayout page) {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), dp(10), dp(12), dp(10));
        panel.setBackground(rounded(Color.WHITE));
        panel.addView(text("本机 P2P 辅助节点", 16, true));
        panel.addView(text("云端账号数据库是主 APK 与管理版共同使用的账号来源；本面板仅管理本机 P2P 辅助节点。", 12, false));
        addNodeServerToggle(panel);
        p2pStatusView = text(readP2PStatus(), 11, false);
        p2pStatusView.setTextColor(Color.rgb(75, 84, 98));
        panel.addView(p2pStatusView);
        Button copyPeer = button("复制管理员节点 ID");
        copyPeer.setOnClickListener(v -> {
            try {
                JSONObject node = new JSONObject(NativeP2P.status());
                String peerId = node.optString("peerId", "");
                if (peerId.isEmpty()) { toast("管理员节点 ID 尚未生成，请稍后再试"); return; }
                ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                clipboard.setPrimaryClip(ClipData.newPlainText("EffectCraft 管理员节点地址", "p2p://" + peerId));
                toast("管理员节点连接地址已复制，可分享给用户首次配对");
            } catch (Exception error) { toast("复制节点 ID 失败：" + error.getMessage()); }
        });
        panel.addView(copyPeer, new LinearLayout.LayoutParams(-1, dp(44)));
        TextView note = text("同一 Wi-Fi 优先直连；跨网络尝试 NAT 打洞，失败后使用动态发现的可用公共 Relay。此节点状态不替代云端账号服务器。", 11, false);
        note.setTextColor(Color.rgb(95, 103, 115));
        panel.addView(note);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = dp(10);
        page.addView(panel, params);
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
        page.addView(text("正在连接共享云端 HTTPS 账号服务，账号和封禁状态在不同地区的设备间同步。", 12, false));
        Button switchServer = button("切换服务器");
        switchServer.setOnClickListener(v -> switchCloudServer());
        page.addView(switchServer, new LinearLayout.LayoutParams(-1, dp(44)));
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
        page.addView(text("云端账号管理：主 APK 与管理版共用同一个 HTTPS 账号数据库。", 14, false));
        page.addView(text("用户和管理员可以处于不同城市、不同 Wi-Fi 或使用移动数据；封禁和解禁状态由云端统一保存。", 13, false));
        page.addView(text("云端 HTTPS 服务器地址", 13, true));
        serverInput = field("由 APK 构建时配置的 Cloudflare HTTPS 地址", false);
        serverInput.setText(server);
        serverInput.setEnabled(false);
        page.addView(serverInput);
        Button switchServer = button("切换服务器");
        page.addView(switchServer, new LinearLayout.LayoutParams(-1, dp(42)));
        switchServer.setOnClickListener(v -> switchCloudServer());
        page.addView(text("管理员账号", 13, true));
        usernameInput = field("admin", false);
        usernameInput.setText("admin");
        page.addView(usernameInput);
        page.addView(text("管理员密码", 13, true));
        passwordInput = field("输入云端管理员密码", true);
        page.addView(passwordInput);
        loginButton = button("登录管理后台");
        page.addView(loginButton, new LinearLayout.LayoutParams(-1, dp(52)));
        loginStatus = text("请输入云端管理员密码。账号登录与管理操作均由云端验证。", 12, false);
        loginStatus.setTextColor(Color.rgb(95, 103, 115));
        page.addView(loginStatus, new LinearLayout.LayoutParams(-1, dp(36)));
        loginButton.setOnClickListener(v -> doAdminLogin());
        page.addView(text("管理员账号固定为 admin；密码由云端 Worker 的 ADMIN_PASSWORD 安全配置项控制。", 12, false));
        setRoot(page);
    }

    private void doAdminLogin() {
        server = trimServer(DEFAULT_SERVER);
        if (server.isEmpty() || !server.startsWith("https://") || !server.endsWith(".workers.dev")) {
            if (loginStatus != null) loginStatus.setText("云端 HTTPS 地址尚未配置，暂时不能登录。请先完成 Cloudflare 部署。");
            return;
        }
        String user = usernameInput.getText().toString().trim();
        // The generated admin password contains no spaces. Ignore accidental
        // leading/trailing whitespace added by mobile clipboard or IME input.
        String pass = passwordInput.getText().toString().trim();
        if (server.isEmpty() || user.isEmpty() || pass.isEmpty()) {
            toast("请填写管理员账号和密码");
            return;
        }
        JSONObject body = new JSONObject();
        try { body.put("username", user); body.put("password", pass); } catch (Exception ignored) {}
        if (loginButton != null) {
            loginButton.setEnabled(false);
            loginButton.setText("正在验证…");
        }
        if (loginStatus != null) loginStatus.setText("正在通过 HTTPS 验证云端管理员账号…");
        requestAsync("POST", "/v1/admin/login", body, false, result -> {
            if (result == null) {
                if (loginButton != null) {
                    loginButton.setEnabled(true);
                    loginButton.setText("登录管理后台");
                }
                // requestAsync writes the precise diagnosis after this callback.
                if (loginStatus != null) loginStatus.setText("验证未完成，正在显示具体失败原因…");
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
            java.util.ArrayList<String> endpoints = cloudServerPool();
            if (!endpoints.contains(server) && server.startsWith("https://")) endpoints.add(0, server);
            if (endpoints.isEmpty()) error = "云端 HTTPS 账号服务器尚未配置";
            for (int index = 0; index < endpoints.size() && result == null; index++) {
                String candidate = endpoints.get(index);
                HttpURLConnection c = null;
                try {
                    URL url = new URL(candidate + path);
                    if (!"https".equalsIgnoreCase(url.getProtocol())) throw new java.io.IOException("只允许 HTTPS 账号入口");
                    c = (HttpURLConnection) url.openConnection();
                    c.setRequestMethod(method);
                    c.setConnectTimeout(6500);
                    c.setReadTimeout(8500);
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
                    if (code >= 500 && index + 1 < endpoints.size()) {
                        error = null;
                        continue;
                    }
                    server = candidate;
                    getPreferences(MODE_PRIVATE).edit().putString("server", server).apply();
                    if (code >= 200 && code < 300) {
                        result = parsed;
                        error = null;
                    } else {
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
                    if (index + 1 < endpoints.size()) error = null;
                    else error = "所有云端 HTTPS 入口均连接失败，最后一个入口 " + candidate + "：" + e.getMessage();
                } finally {
                    if (c != null) c.disconnect();
                }
            }
            JSONObject finalResult = result;
            String finalError = error;
            runOnUiThread(() -> {
                if (finalError != null) {
                    toast(finalError);
                    if (auth && (finalError.contains("401") || finalError.contains("登录已失效") || finalError.contains("账号权限不足"))) showLogin();
                }
                if (callback != null) callback.done(finalResult);
                if (finalError != null && "/v1/admin/login".equals(path) && loginStatus != null) {
                    loginStatus.setText("登录失败诊断：" + finalError);
                }
            });
        });
    }

    private void loadUsers(String query) {
        String encoded;
        try { encoded = URLEncoder.encode(query, "UTF-8"); } catch (Exception e) { encoded = ""; }
        requestAsync("GET", "/v1/admin/users?q=" + encoded, null, true, result -> {
            if (result == null) {
                adminToken = "";
                getPreferences(MODE_PRIVATE).edit().remove("admin_token").apply();
                showLogin();
                return;
            }
            JSONArray users = result.optJSONArray("users");
            int totalCount = result.optInt("total_count", users == null ? 0 : users.length());
            int filteredCount = result.optInt("filtered_count", users == null ? 0 : users.length());
            showUsers(users, totalCount, filteredCount);
        });
    }

    private void addAccountServiceControl(LinearLayout page) {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), dp(8), dp(12), dp(8));
        panel.setBackground(rounded(Color.WHITE));
        panel.addView(text("云端账号服务器", 16, true));
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        TextView label = text("账号服务开关", 14, true);
        row.addView(label, new LinearLayout.LayoutParams(0, dp(48), 1));
        Switch control = new Switch(this);
        control.setTextOn("开启");
        control.setTextOff("关闭");
        control.setChecked(true);
        control.setEnabled(false);
        row.addView(control, new LinearLayout.LayoutParams(-2, dp(48)));
        panel.addView(row);
        TextView note = text("关闭后，用户端不能注册、登录或验证账号；管理员仍可进入本后台并重新开启。此开关控制云端账号服务，不会删除账号资料。", 11, false);
        note.setTextColor(Color.rgb(95, 103, 115));
        panel.addView(note);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = dp(10);
        page.addView(panel, params);
        accountServiceSwitch = control;
        control.setOnCheckedChangeListener((button, enabled) -> setAccountServiceEnabled(enabled, control));
        requestAsync("GET", "/v1/admin/server", null, true, result -> {
            if (result == null) {
                control.setEnabled(false);
                return;
            }
            accountServiceSwitchChanging = true;
            control.setChecked(result.optBoolean("enabled", true));
            accountServiceSwitchChanging = false;
            control.setEnabled(true);
        });
    }

    private void setAccountServiceEnabled(boolean enabled, Switch control) {
        if (accountServiceSwitchChanging) return;
        control.setEnabled(false);
        JSONObject body = new JSONObject();
        try { body.put("enabled", enabled); } catch (Exception ignored) {}
        requestAsync("POST", "/v1/admin/server", body, true, result -> {
            if (result == null) {
                accountServiceSwitchChanging = true;
                control.setChecked(!enabled);
                accountServiceSwitchChanging = false;
                control.setEnabled(true);
                return;
            }
            boolean confirmed = result.optBoolean("enabled", enabled);
            accountServiceSwitchChanging = true;
            control.setChecked(confirmed);
            accountServiceSwitchChanging = false;
            control.setEnabled(true);
            toast(confirmed ? "云端账号服务器已开启" : "云端账号服务器已关闭；账号数据保留，管理员仍可重新开启");
        });
    }

    private void showUsers(JSONArray users, int totalCount, int filteredCount) {
        LinearLayout page = column();
        TextView title = text("EffectCraft 账号管理", 22, true);
        page.addView(title, new LinearLayout.LayoutParams(-1, dp(44)));

        accountCountView = text("云端已注册账号：" + totalCount + " 个", 18, true);
        accountCountView.setTextColor(Color.rgb(40, 90, 150));
        page.addView(accountCountView, new LinearLayout.LayoutParams(-1, dp(36)));
        accountFilterCountView = text("当前显示 " + (users == null ? 0 : users.length()) + " 个 / 匹配 " + filteredCount + " 个", 12, false);
        accountFilterCountView.setTextColor(Color.rgb(95, 103, 115));
        page.addView(accountFilterCountView, new LinearLayout.LayoutParams(-1, dp(28)));

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        Button switchServer = button("切换服务器");
        Button refresh = button("刷新账号");
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, dp(44), 1);
        half.rightMargin = dp(4);
        top.addView(switchServer, half);
        LinearLayout.LayoutParams half2 = new LinearLayout.LayoutParams(0, dp(44), 1);
        half2.leftMargin = dp(4);
        top.addView(refresh, half2);
        switchServer.setOnClickListener(v -> switchCloudServer());
        refresh.setOnClickListener(v -> loadUsers(searchInput == null ? "" : searchInput.getText().toString()));
        page.addView(top);

        addAccountServiceControl(page);
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
                addUserRow(user, i);
                return;
            }
        }
        addUserRow(user);
    }

    private void addUserRow(JSONObject user) {
        addUserRow(user, -1);
    }

    private void addUserRow(JSONObject user, int position) {
        String id = user.optString("id");
        String name = user.optString("name", "未命名");
        String qq = user.optString("qq", "");
        String wechat = user.optString("wechat", "");
        String until = user.optString("banned_until", "");
        boolean banned = !until.isEmpty() && !until.equals("null");
        boolean permanent = "permanent".equalsIgnoreCase(until);

        // One compact horizontal row: avatar on the left, ban/unban controls on the right.
        // The avatar alone opens the user detail sheet; passwords are never requested or displayed.
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.HORIZONTAL);
        card.setGravity(Gravity.CENTER_VERTICAL);
        card.setPadding(dp(9), dp(8), dp(9), dp(8));
        card.setBackground(rounded(Color.WHITE));
        card.setTag(id);
        LinearLayout.LayoutParams cardParams = new LinearLayout.LayoutParams(-1, ViewGroup.LayoutParams.WRAP_CONTENT);
        cardParams.bottomMargin = dp(8);

        LinearLayout details = new LinearLayout(this);
        details.setOrientation(LinearLayout.HORIZONTAL);
        details.setGravity(Gravity.CENTER_VERTICAL);
        card.addView(details, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));

        String avatarUrl = user.optString("avatar_url", "");
        View avatarView;
        if (!avatarUrl.isEmpty()) {
            ImageView avatar = new ImageView(this);
            avatar.setScaleType(ImageView.ScaleType.CENTER_CROP);
            avatar.setBackground(rounded(Color.rgb(66, 105, 180)));
            avatar.setClipToOutline(true);
            avatar.setContentDescription("点击查看用户信息");
            details.addView(avatar, new LinearLayout.LayoutParams(dp(48), dp(48)));
            loadAvatar(avatar, avatarUrl);
            avatarView = avatar;
        } else {
            TextView avatar = text(name.isEmpty() ? "?" : name.substring(0, 1), 20, true);
            avatar.setGravity(Gravity.CENTER);
            avatar.setTextColor(Color.WHITE);
            avatar.setBackground(rounded(Color.rgb(66, 105, 180)));
            avatar.setContentDescription("点击查看用户信息");
            details.addView(avatar, new LinearLayout.LayoutParams(dp(48), dp(48)));
            avatarView = avatar;
        }
        avatarView.setOnClickListener(v -> showUserDetails(user));

        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(dp(9), 0, dp(5), 0);
        TextView label = text(name, 14, true);
        TextView ids = text("QQ " + (qq.isEmpty() ? "未填写" : qq) + " · 微信 " + (wechat.isEmpty() ? "未填写" : wechat), 10, false);
        ids.setTextColor(Color.rgb(95, 103, 115));
        label.setMaxLines(1);
        ids.setMaxLines(2);
        info.addView(label);
        info.addView(ids);
        if (banned) {
            TextView ban = text(permanent ? "永久封禁" : "封禁至 " + until, 10, true);
            ban.setTextColor(Color.rgb(180, 58, 58));
            info.addView(ban);
        } else {
            TextView normal = text("正常", 10, true);
            normal.setTextColor(Color.rgb(45, 135, 80));
            info.addView(normal);
        }
        details.addView(info, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.VERTICAL);
        actions.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams actionsParams = new LinearLayout.LayoutParams(dp(84), ViewGroup.LayoutParams.WRAP_CONTENT);
        Button banButton = button("封禁");
        Button unbanButton = button("解禁");
        banButton.setTextSize(12);
        unbanButton.setTextSize(12);
        banButton.setMinHeight(0);
        unbanButton.setMinHeight(0);
        banButton.setPadding(dp(2), 0, dp(2), 0);
        unbanButton.setPadding(dp(2), 0, dp(2), 0);
        unbanButton.setEnabled(banned);
        actions.addView(banButton, new LinearLayout.LayoutParams(-1, dp(38)));
        LinearLayout.LayoutParams unbanParams = new LinearLayout.LayoutParams(-1, dp(38));
        unbanParams.topMargin = dp(4);
        actions.addView(unbanButton, unbanParams);
        card.addView(actions, actionsParams);
        banButton.setOnClickListener(v -> chooseBan(id));
        unbanButton.setOnClickListener(v -> unban(id));

        if (position >= 0 && position <= rows.getChildCount()) {
            rows.addView(card, position, cardParams);
        } else {
            rows.addView(card, cardParams);
        }
    }

    private void loadAvatar(ImageView view, String uri) {
        io.execute(() -> {
            HttpURLConnection c = null;
            try {
                Bitmap bitmap;
                final String localPrefix = "data:image/jpeg;base64,";
                if (uri.startsWith(localPrefix)) {
                    // Account avatars selected from the Android Photo Picker are
                    // compact JPEG data URIs stored directly in the local account DB.
                    byte[] bytes = Base64.decode(uri.substring(localPrefix.length()), Base64.DEFAULT);
                    if (bytes.length == 0 || bytes.length > 96 * 1024) return;
                    bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
                } else {
                    c = (HttpURLConnection) new URL(uri).openConnection();
                    c.setConnectTimeout(5000);
                    c.setReadTimeout(5000);
                    c.setInstanceFollowRedirects(true);
                    try (InputStream in = c.getInputStream()) {
                        bitmap = BitmapFactory.decodeStream(in);
                    }
                }
                if (bitmap != null) runOnUiThread(() -> view.setImageBitmap(bitmap));
            } catch (Exception ignored) {
                // Keep the colored placeholder when the optional avatar cannot be loaded.
            } finally {
                if (c != null) c.disconnect();
            }
        });
    }

    private void showUserDetails(JSONObject user) {
        String avatar = user.optString("avatar_url");
        String avatarDescription = avatar.startsWith("data:image/")
            ? "本机相册头像（已压缩保存）" : avatar;
        String until = user.optString("banned_until", "");
        String banStatus = until.isEmpty() || until.equals("null")
            ? "未封禁"
            : ("permanent".equalsIgnoreCase(until) ? "永久封禁" : "临时封禁，截止：" + until);
        String message = "名字：" + user.optString("name") +
                "\nQQ号：" + user.optString("qq") +
                "\n微信号：" + user.optString("wechat") +
                "\n注册时间：" + user.optString("created_at") +
                "\n头像：" + avatarDescription +
                "\n账号状态：" + banStatus +
                "\n封禁原因：" + user.optString("ban_reason");
        new AlertDialog.Builder(this).setTitle("账号个人信息")
                .setMessage(message)
                .setPositiveButton("OK", null).show();
    }

    private void chooseBan(String id) {
        new AlertDialog.Builder(this)
            .setTitle("选择封禁方式")
            .setItems(new String[] {"临时封号（设置到期时间）", "永久封号（需管理员手动解禁）"}, (dialog, which) -> {
                if (which == 0) chooseTemporaryBan(id);
                else askPermanentBanReason(id);
            })
            .setNegativeButton("取消", null)
            .show();
    }

    private void chooseTemporaryBan(String id) {
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
                EditText reason = new EditText(this);
                reason.setHint("填写封禁原因（必填）");
                reason.setMinLines(2);
                reason.setGravity(Gravity.TOP);
                new AlertDialog.Builder(this).setTitle("确认临时封禁")
                    .setMessage("封禁截止：" + selected.getTime())
                    .setView(reason)
                    .setNegativeButton("取消", null)
                    .setPositiveButton("确认封禁", (dialog, which) -> {
                        String why = reason.getText().toString().trim();
                        if (why.isEmpty()) { toast("请填写封禁原因"); return; }
                        submitBan(id, Instant.ofEpochMilli(selected.getTimeInMillis()).toString(), why);
                    })
                    .show();
            }, selected.get(Calendar.HOUR_OF_DAY), selected.get(Calendar.MINUTE), true).show();
        }, selected.get(Calendar.YEAR), selected.get(Calendar.MONTH), selected.get(Calendar.DAY_OF_MONTH)).show();
    }

    private void askPermanentBanReason(String id) {
        EditText reason = new EditText(this);
        reason.setHint("填写永久封禁原因（必填）");
        reason.setMinLines(2);
        reason.setGravity(Gravity.TOP);
        new AlertDialog.Builder(this).setTitle("确认永久封禁")
            .setMessage("永久封禁不会自动到期，只有管理员执行解禁后才能恢复。")
            .setView(reason)
            .setNegativeButton("取消", null)
            .setPositiveButton("确认永久封禁", (dialog, which) -> {
                String why = reason.getText().toString().trim();
                if (why.isEmpty()) { toast("请填写封禁原因"); return; }
                submitBan(id, "permanent", why);
            })
            .show();
    }

    private void submitBan(String id, String until, String reason) {
        JSONObject body = new JSONObject();
        try {
            body.put("banned_until", until);
            body.put("reason", reason);
        } catch (Exception ignored) {}
        requestAsync("POST", "/v1/admin/users/" + id + "/ban", body, true, result -> {
            if (result != null) {
                int delivered = result.optInt("notification_delivered", 0);
                String status = "permanent".equalsIgnoreCase(until) ? "永久封禁" : "临时封禁";
                toast(delivered > 0
                    ? status + "已生效，并已通知在线设备（" + delivered + " 个连接）"
                    : status + "记录已保存；离线设备联网后同步");
                updateVisibleUser(result.optJSONObject("user"));
            }
        });
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
        p2pUiHandler.removeCallbacks(p2pStatusRefresh);
        super.onDestroy();
        io.shutdownNow();
    }
}
