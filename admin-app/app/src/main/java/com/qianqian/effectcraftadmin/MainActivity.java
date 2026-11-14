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
    private static final String DEFAULT_SERVER = "http://127.0.0.1:8787";
    private String server = DEFAULT_SERVER;
    private String firstAdminPassword;
    private String adminToken = "";
    private LinearLayout root;
    private LinearLayout rows;
    private EditText usernameInput;
    private EditText passwordInput;
    private EditText searchInput;
    private Button loginButton;
    private TextView loginStatus;
    private TextView p2pStatusView;
    private String serviceStartError = "";
    private boolean serverToggleChanging = false;
    private boolean cloudServerToggleChanging = false;
    private boolean cloudServerEnabled = true;
    private final Handler p2pUiHandler = new Handler(Looper.getMainLooper());
    private final Runnable p2pStatusRefresh = new Runnable() {
        @Override public void run() {
            if (p2pStatusView != null) p2pStatusView.setText(readP2PStatus());
            p2pUiHandler.postDelayed(this, 5000);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        AdminAccountVpnService.attachActivity(this);
        boolean cloudMode = CloudflareProxyPool.isCloudflareUrl(BuildConfig.ACCOUNT_API_URL);
        firstAdminPassword = cloudMode ? null : LanAccountServer.ensureAdminPassword(this);
        if (!cloudMode && isNodeServerEnabled()) {
            try { startNodeServerService(); }
            catch (RuntimeException ignored) { /* The login screen will keep the server error visible. */ }
        }
        p2pUiHandler.postDelayed(p2pStatusRefresh, 2500);
        getWindow().setStatusBarColor(Color.rgb(245, 247, 250));
        getWindow().setNavigationBarColor(Color.rgb(245, 247, 250));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        server = trimServer(cloudMode ? BuildConfig.ACCOUNT_API_URL : DEFAULT_SERVER);
        String savedServer = getPreferences(MODE_PRIVATE).getString("server", "");
        adminToken = savedServer.equals(server)
            ? getPreferences(MODE_PRIVATE).getString("admin_token", "") : "";
        if (!savedServer.isEmpty() && !savedServer.equals(server)) {
            getPreferences(MODE_PRIVATE).edit().remove("admin_token").apply();
        }
        if (!adminToken.isEmpty()) {
            showConnecting("正在验证本机管理员账号…");
            loadUsers("");
        } else {
            showLogin();
        }
    }

    private boolean isCloudflareMode() {
        return CloudflareProxyPool.isCloudflareUrl(server);
    }

    private String configuredAccountServer() {
        String configured = BuildConfig.ACCOUNT_API_URL == null ? "" : BuildConfig.ACCOUNT_API_URL.trim();
        return CloudflareProxyPool.isCloudflareUrl(configured) ? trimServer(configured) : DEFAULT_SERVER;
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
        TextView label = text("本机局域网服务开关", 14, true);
        row.addView(label, new LinearLayout.LayoutParams(0, dp(48), 1));
        Switch control = new Switch(this);
        control.setTextOn("开启");
        control.setTextOff("关闭");
        control.setChecked(isNodeServerEnabled());
        control.setOnCheckedChangeListener((button, enabled) -> setNodeServerEnabled(enabled, control));
        row.addView(control, new LinearLayout.LayoutParams(-2, dp(48)));
        parent.addView(row);
        parent.addView(text("只控制本机局域网 SQLite 服务；不代表 Ae 云端服务器的总开关。", 11, false));
    }

    private void addCloudServerToggle(LinearLayout parent) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        TextView label = text("Ae 服务器总开关", 14, true);
        row.addView(label, new LinearLayout.LayoutParams(0, dp(48), 1));
        Switch control = new Switch(this);
        control.setTextOn("开启");
        control.setTextOff("关闭");
        control.setChecked(false);
        control.setEnabled(false);
        control.setOnCheckedChangeListener((button, enabled) -> setCloudServerEnabled(enabled, control));
        row.addView(control, new LinearLayout.LayoutParams(-2, dp(48)));
        parent.addView(row);
        parent.addView(text("关闭后，所有主 APK 自动退出编辑状态并显示停服页面；开启后，在线设备收到恢复通知。离线设备下次连接时同步状态。", 11, false));

        requestAsync("GET", "/v1/admin/server", null, true, result -> {
            if (result == null || result.optJSONObject("server") == null) {
                control.setEnabled(false);
                toast("无法读取 Ae 服务器状态，开关保持锁定");
                return;
            }
            cloudServerEnabled = result.optJSONObject("server").optBoolean("enabled", true);
            cloudServerToggleChanging = true;
            control.setChecked(cloudServerEnabled);
            cloudServerToggleChanging = false;
            control.setEnabled(true);
        });
    }

    private void setCloudServerEnabled(boolean enabled, Switch control) {
        if (cloudServerToggleChanging) return;
        boolean previous = cloudServerEnabled;
        control.setEnabled(false);
        JSONObject body = new JSONObject();
        try { body.put("enabled", enabled); }
        catch (Exception error) {
            control.setEnabled(true);
            cloudServerToggleChanging = true;
            control.setChecked(previous);
            cloudServerToggleChanging = false;
            toast("服务器开关数据准备失败");
            return;
        }
        requestAsync("POST", "/v1/admin/server", body, true, result -> {
            JSONObject state = result == null ? null : result.optJSONObject("server");
            if (state == null) {
                cloudServerToggleChanging = true;
                control.setChecked(previous);
                cloudServerToggleChanging = false;
                cloudServerEnabled = previous;
                control.setEnabled(true);
                return;
            }
            cloudServerEnabled = state.optBoolean("enabled", previous);
            int delivered = result.optInt("notification_delivered", 0);
            cloudServerToggleChanging = true;
            control.setChecked(cloudServerEnabled);
            cloudServerToggleChanging = false;
            control.setEnabled(true);
            if (cloudServerEnabled) {
                toast("Ae 服务器已开启，已向 " + delivered + " 台在线设备发送恢复通知");
            } else {
                toast("Ae 服务器已关闭，已向 " + delivered + " 台在线设备发送停服通知");
            }
        });
    }

    /** The administrator phone is the account authority; P2P carries authenticated account RPC. */
    private void addGlobalNodePanel(LinearLayout page) {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), dp(10), dp(12), dp(10));
        panel.setBackground(rounded(Color.WHITE));
        panel.addView(text(isCloudflareMode() ? "P2P 节点网络（独立功能）" : "管理员手机账号节点", 16, true));
        panel.addView(text(isCloudflareMode()
            ? "账号注册、登录、查询、封禁和解禁由 Cloudflare Workers + D1 统一处理。本机节点开关只控制独立 P2P 节点，不替代云端账号服务。"
            : "账号数据保存在本机 SQLite；用户注册、登录、资料修改和封禁状态均由本机校验。", 12, false));
        if (isCloudflareMode()) addCloudServerToggle(panel);
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
        TextView note = text("同一 Wi-Fi 优先直连；跨网络尝试 NAT 打洞，失败后使用动态发现的可用公共 Relay。用户通过加密 P2P 请求访问本机账号库。首次配对时可分享本节点 ID。", 11, false);
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
        page.addView(text(isCloudflareMode()
            ? "正在通过内置 Cloudflare WARP 加密隧道连接账号服务；无需经过管理员手机中转。"
            : "正在连接本机账号数据库，并通过 P2P 为其他手机提供加密账号服务。", 12, false));
        Button retry = button("重新连接");
        retry.setOnClickListener(v -> {
            showConnecting("正在重新连接本机账号服务…");
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
        TextView title = text("Ae账号管理", 24, true);
        page.addView(title, new LinearLayout.LayoutParams(-1, dp(56)));
        page.addView(text(isCloudflareMode()
            ? "管理端连接统一 Cloudflare 账号服务；网络不通时自动检测可用的公开 HTTPS 隧道。"
            : "本机账号管理：账号数据库保存在这部管理员手机上。", 14, false));
        page.addView(text(isCloudflareMode()
            ? "主 APK 和管理版 APK 共用同一 Cloudflare 账号数据库。"
            : "其他用户无需与管理员处于同一 Wi-Fi；主 APK 自动发现本机节点，并通过加密 P2P 通道注册、登录和核验封禁状态。", 13, false));
        if (!isCloudflareMode()) addNodeServerToggle(page);
        page.addView(text("管理员账号", 13, true));
        usernameInput = field("admin", false);
        usernameInput.setText("admin");
        page.addView(usernameInput);
        page.addView(text("管理员密码", 13, true));
        passwordInput = field("输入本机管理员密码；首次设置输入新密码", true);
        page.addView(passwordInput);
        loginButton = button("登录管理后台");
        page.addView(loginButton, new LinearLayout.LayoutParams(-1, dp(52)));
        loginStatus = text("请输入管理员密码；本机注册人数为 0 时，首次登录会采用本次输入密码。", 12, false);
        loginStatus.setTextColor(Color.rgb(95, 103, 115));
        page.addView(loginStatus, new LinearLayout.LayoutParams(-1, dp(36)));
        loginButton.setOnClickListener(v -> doAdminLogin());
        page.addView(text("管理员账号固定为 admin。本机尚无注册账号时，首次登录会将本次输入的密码保存为管理员密码；注册账号后不再允许通过此入口重设。", 12, false));
        setRoot(page);
        if (firstAdminPassword != null) {
            String password = firstAdminPassword;
            firstAdminPassword = null;
            new AlertDialog.Builder(this)
                .setTitle("本机管理员初始密码")
                .setMessage("这是本机账号数据库生成的唯一初始管理员密码。请先复制并妥善保存，后续登录需要使用它：\\n\\n" + password)
                .setPositiveButton("我已保存", (dialog, which) -> LanAccountServer.acknowledgeAdminPasswordSaved(this))
                .setCancelable(false)
                .show();
        }
    }

    private void doAdminLogin() {
        server = trimServer(DEFAULT_SERVER);
        String user = usernameInput.getText().toString().trim();
        // The generated admin password contains no spaces. Ignore accidental
        // leading/trailing whitespace added by mobile clipboard or IME input.
        String pass = passwordInput.getText().toString().trim();
        server = configuredAccountServer();
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
        if (loginStatus != null) loginStatus.setText(isCloudflareMode()
            ? "正在通过 Cloudflare WARP 加密隧道验证管理员账号…"
            : "正在等待本机 SQLite 服务就绪并校验管理员密码…");
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

    private static final class AdminCredentialMismatchException extends Exception {
        AdminCredentialMismatchException(String message) { super(message); }
    }

    private interface JsonCallback { void done(JSONObject result); }

    /**
     * Wait until the foreground service has bound its loopback HTTP endpoint and
     * SQLite has passed an integrity check. The Activity can be visible before
     * Android has finished creating the foreground service, so a fixed immediate
     * login request races the service startup.
     */
    private void awaitLocalAccountService() throws Exception {
        if (!serviceStartError.isEmpty()) throw new java.io.IOException(serviceStartError);
        long deadline = System.currentTimeMillis() + 15000L;
        String lastProblem = "后台服务仍在启动";
        while (System.currentTimeMillis() < deadline) {
            HttpURLConnection probe = null;
            try {
                URL healthUrl = new URL(DEFAULT_SERVER + "/health");
                probe = (HttpURLConnection) healthUrl.openConnection();
                probe.setConnectTimeout(900);
                probe.setReadTimeout(1200);
                probe.setRequestMethod("GET");
                probe.setRequestProperty("Accept", "application/json");
                int code = probe.getResponseCode();
                InputStream input = code >= 200 && code < 300 ? probe.getInputStream() : probe.getErrorStream();
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                if (input != null) {
                    try (InputStream stream = input) {
                        byte[] buffer = new byte[1024];
                        int count;
                        while ((count = stream.read(buffer)) > 0) bytes.write(buffer, 0, count);
                    }
                }
                JSONObject health = new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
                if (code == 200 && health.optBoolean("ready", false)
                    && "ready".equals(health.optString("database", ""))) {
                    return;
                }
                Object detail = health.opt("detail");
                if (detail instanceof JSONObject) lastProblem = ((JSONObject) detail).optString("message", detail.toString());
                else lastProblem = detail == null ? ("健康检查返回 HTTP " + code) : detail.toString();
            } catch (Exception error) {
                lastProblem = error.getClass().getSimpleName()
                    + (error.getMessage() == null ? "" : "：" + error.getMessage());
            } finally {
                if (probe != null) probe.disconnect();
            }
            try { Thread.sleep(350L); }
            catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new java.io.IOException("等待本机账号服务时被中断");
            }
        }
        throw new java.io.IOException("等待本机 SQLite 账号服务超时（15秒）：" + lastProblem);
    }

    private void requestAsync(String method, String path, JSONObject body, boolean auth, JsonCallback callback) {
        io.execute(() -> {
            JSONObject result = null;
            String error = null;
            HttpURLConnection localConnection = null;
            try {
                int code;
                JSONObject parsed;
                if (isCloudflareMode()) {
                    CloudflareProxyPool.ApiResponse response = CloudflareProxyPool.request(
                        this, server, method, path, body, auth ? adminToken : ""
                    );
                    code = response.status;
                    parsed = response.body;
                } else {
                    if (path.startsWith("/v1/admin/")) {
                        awaitLocalAccountService();
                        if ("/v1/admin/login".equals(path)) {
                            String candidate = body == null ? "" : body.optString("password", "");
                            if (!LanAccountServer.verifyAdminPasswordOnDevice(getApplicationContext(), candidate)) {
                                if (!LanAccountServer.adoptAdminPasswordIfNoRegisteredUsers(
                                    getApplicationContext(), candidate)) {
                                    throw new AdminCredentialMismatchException(
                                        "管理员密码校验失败。只有本机账号库确认为 0 个注册账号时，才允许首次设置/更改管理员密码；当前未修改密码。");
                                }
                            }
                        }
                    }
                    URL url = new URL(server + path);
                    if (!"http".equalsIgnoreCase(url.getProtocol())
                        || !"127.0.0.1".equals(url.getHost()) || url.getPort() != 8787) {
                        throw new java.io.IOException("账号管理界面只允许访问本机管理员账号服务");
                    }
                    localConnection = (HttpURLConnection) url.openConnection();
                    localConnection.setRequestMethod(method);
                    localConnection.setConnectTimeout(8000);
                    localConnection.setReadTimeout(10000);
                    localConnection.setRequestProperty("Accept", "application/json");
                    if (auth && !adminToken.isEmpty()) {
                        localConnection.setRequestProperty("Authorization", "Bearer " + adminToken);
                    }
                    if (body != null) {
                        localConnection.setDoOutput(true);
                        localConnection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                        try (OutputStream out = localConnection.getOutputStream()) { out.write(bytes); }
                    }
                    code = localConnection.getResponseCode();
                    InputStream input = code >= 200 && code < 400
                        ? localConnection.getInputStream() : localConnection.getErrorStream();
                    ByteArrayOutputStream data = new ByteArrayOutputStream();
                    if (input != null) {
                        try (InputStream stream = input) {
                            byte[] buffer = new byte[4096];
                            int n;
                            while ((n = stream.read(buffer)) > 0) data.write(buffer, 0, n);
                        }
                    }
                    parsed = new JSONObject(new String(data.toByteArray(), StandardCharsets.UTF_8));
                }

                if (code >= 200 && code < 300) {
                    result = parsed;
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
            } catch (AdminCredentialMismatchException e) {
                error = e.getMessage();
            } catch (Exception e) {
                error = (isCloudflareMode() ? "无法连接 Cloudflare 云端账号服务：" : "无法连接本机账号服务：")
                    + (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
            } finally {
                if (localConnection != null) localConnection.disconnect();
            }
            JSONObject finalResult = result;
            String finalError = error;
            runOnUiThread(() -> {
                if (finalError != null) {
                    toast(finalError);
                    if (auth && (finalError.contains("401") || finalError.contains("登录已失效")
                        || finalError.contains("账号权限不足"))) showLogin();
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
        TextView title = text("账号管理 · 共 " + (users == null ? 0 : users.length()) + " 个账号", 22, true);
        top.addView(title, new LinearLayout.LayoutParams(0, dp(48), 1));
        Button refresh = button("刷新");
        top.addView(refresh);
        refresh.setOnClickListener(v -> loadUsers(searchInput == null ? "" : searchInput.getText().toString()));
        page.addView(top);
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
        String message = "名字：" + user.optString("name") +
                "\nQQ号：" + user.optString("qq") +
                "\n微信号：" + user.optString("wechat") +
                "\n注册时间：" + user.optString("created_at") +
                "\n头像：" + avatarDescription +
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

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == AdminAccountVpnService.PERMISSION_REQUEST_CODE) {
            AdminAccountVpnService.onPermissionResult(resultCode);
        }
    }

    @Override protected void onDestroy() {
        p2pUiHandler.removeCallbacks(p2pStatusRefresh);
        super.onDestroy();
        io.shutdownNow();
    }
}
