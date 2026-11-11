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
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
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
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.spec.RSAKeyGenParameterSpec;
import java.util.UUID;
import android.util.Base64;
import java.time.Instant;
import java.util.Calendar;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private static final String DEFAULT_SERVER = "http://127.0.0.1:8788";
    private static final String PERMANENT_BAN_UNTIL = "9999-12-31T23:59:59Z";
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
        if (getPreferences(MODE_PRIVATE).getBoolean("account_server_enabled", true)) {
            Intent accountServerIntent = new Intent(this, AccountServerService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(accountServerIntent);
            else startService(accountServerIntent);
        }
        if (getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE).getBoolean("node_enabled", false)) {
            Intent nodeIntent = new Intent(this, LanServerService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(nodeIntent);
            else startService(nodeIntent);
        }
        getWindow().setStatusBarColor(Color.rgb(245, 247, 250));
        getWindow().setNavigationBarColor(Color.rgb(245, 247, 250));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        server = DEFAULT_SERVER;
        adminToken = getPreferences(MODE_PRIVATE).getString("admin_token", "");
        if (!adminToken.isEmpty()) { showConnecting("正在读取管理员手机本地账号数据库…"); loadUsers(""); }
        else { showLogin(); }
    }

    /** Server-authoritative global node switch; never trust a local preference for this control. */

    /** Independent local account-server switch; does not control the P2P network switch below. */
    private void addLocalAccountServerPanel(LinearLayout page) {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), dp(10), dp(12), dp(10));
        panel.setBackground(rounded(Color.WHITE));
        panel.addView(text("管理员手机主服务器", 16, true));
        TextView status = text("", 13, false);
        panel.addView(status);
        Button toggle = button("");
        panel.addView(toggle, new LinearLayout.LayoutParams(-1, dp(46)));
        Runnable refresh = () -> {
            boolean enabled = getPreferences(MODE_PRIVATE).getBoolean("account_server_enabled", true);
            String ip = LanAccountServer.getWifiIpv4();
            status.setText(enabled
                ? (ip.isEmpty() ? "账号服务已启用 · 等待 Wi-Fi 连接" : "账号服务已启用 · " + ip + ":8788")
                : "账号服务已关闭 · 主 APK 暂时无法注册、登录和验证");
            toggle.setText(enabled ? "关闭账号主服务器" : "开启账号主服务器");
        };
        refresh.run();
        toggle.setOnClickListener(v -> {
            boolean enabled = getPreferences(MODE_PRIVATE).getBoolean("account_server_enabled", true);
            boolean next = !enabled;
            getPreferences(MODE_PRIVATE).edit().putBoolean("account_server_enabled", next).apply();
            Intent intent = new Intent(this, AccountServerService.class);
            if (next) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent);
                else startService(intent);
                toast("正在启动管理员手机账号服务器");
            } else {
                stopService(intent);
                toast("账号主服务器已关闭");
            }
            refresh.run();
        });
        TextView note = text("账号服务器开关独立于节点互联开关。关闭后，用户端无法注册、登录和验证。", 11, false);
        note.setTextColor(Color.rgb(95, 103, 115));
        panel.addView(note);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = dp(10);
        page.addView(panel, params);
    }

    private void addGlobalNodePanel(LinearLayout page) {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), dp(10), dp(12), dp(10));
        panel.setBackground(rounded(Color.WHITE));
        panel.addView(text("节点互联网络开关", 16, true));
        TextView status = text("", 13, false);
        TextView count = text("", 12, false);
        panel.addView(status);
        panel.addView(count);
        Button toggle = button("");
        panel.addView(toggle, new LinearLayout.LayoutParams(-1, dp(46)));
        Runnable refresh = () -> {
            boolean enabled = getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE).getBoolean("node_enabled", false);
            boolean running = getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE).getBoolean("node_running", false);
            int peers = LanPeerDiscovery.getSavedPeers(this).length();
            status.setText(enabled ? (running ? "状态：已开启 · 本机节点正在运行" : "状态：已开启 · 正在等待节点服务启动") : "状态：已关闭 · 本机节点已停止");
            count.setText("已发现附近节点：" + peers + " 台（当前仅支持同一 Wi-Fi）");
            toggle.setText(enabled ? "关闭节点互联网络" : "开启节点互联网络");
        };
        refresh.run();
        toggle.setOnClickListener(v -> {
            boolean enabled = getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE).getBoolean("node_enabled", false);
            boolean next = !enabled;
            getSharedPreferences(LanPeerDiscovery.PREFS, MODE_PRIVATE).edit().putBoolean("node_enabled", next).apply();
            Intent intent = new Intent(this, LanServerService.class);
            if (next) {
                try {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent);
                    else startService(intent);
                    toast("节点网络已开启，正在尝试发现附近节点");
                } catch (Exception e) { toast("节点服务启动失败：" + e.getMessage()); }
            } else {
                stopService(intent);
                toast("节点网络已关闭");
            }
            refresh.run();
        });
        TextView note = text("此开关独立于账号服务器开关。当前已实现同一 Wi-Fi 的节点广播与发现；跨地区公网穿透和远程统一控制尚未完成。", 11, false);
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
        page.addView(text("管理员手机本地 SQLite 账号数据库；账号资料不会上传到第三方云平台。", 12, false));
        Button retry = button("重新连接");
        retry.setOnClickListener(v -> {
            showConnecting("正在重新读取管理员手机本地账号数据库…");
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
        page.addView(text("本机就是账号主服务器，账号资料保存在这台管理员手机，不使用 Cloudflare 或外国云端数据库。", 13, false));
        page.addView(text("服务器地址", 13, true));
        serverInput = field("本机账号服务器", false);
        serverInput.setText(DEFAULT_SERVER);
        serverInput.setEnabled(false);
        page.addView(serverInput);
        page.addView(text("管理员密码", 13, true));
        passwordInput = field("输入管理员密码", true);
        page.addView(passwordInput);
        loginButton = button("登录本机管理员");
        page.addView(loginButton, new LinearLayout.LayoutParams(-1, dp(52)));
        loginStatus = text("首次登录后保存本机登录凭据；账号服务器在管理员手机后台运行。", 12, false);
        loginStatus.setTextColor(Color.rgb(95, 103, 115));
        page.addView(loginStatus, new LinearLayout.LayoutParams(-1, dp(36)));
        loginButton.setOnClickListener(v -> doAdminLogin());
        page.addView(text("更换手机或清除应用数据后，需要重新输入管理员密码。", 12, false));
        // Keep the server switch reachable even while logged out, so it can be turned back on.
        addLocalAccountServerPanel(page);
        setRoot(page);
    }

    private static final String ADMIN_KEY_ALIAS = "effectcraft_admin_device_v1";

    private boolean hasAdminDeviceKey() {
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            return store.containsAlias(ADMIN_KEY_ALIAS) &&
                getPreferences(MODE_PRIVATE).contains("admin_device_id");
        } catch (Exception e) { return false; }
    }

    private KeyPair ensureAdminDeviceKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ADMIN_KEY_ALIAS)) {
            KeyPairGenerator generator = KeyPairGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore"
            );
            KeyGenParameterSpec spec = new KeyGenParameterSpec.Builder(
                ADMIN_KEY_ALIAS, KeyProperties.PURPOSE_SIGN
            ).setDigests(KeyProperties.DIGEST_SHA256)
             .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1)
             .setKeySize(2048)
             .build();
            generator.initialize(spec);
            generator.generateKeyPair();
            store.load(null);
        }
        java.security.cert.Certificate certificate = store.getCertificate(ADMIN_KEY_ALIAS);
        if (certificate == null) throw new java.io.IOException("本机安全密钥创建失败");
        return new KeyPair(certificate.getPublicKey(), (PrivateKey) store.getKey(ADMIN_KEY_ALIAS, null));
    }

    private String deviceId() {
        android.content.SharedPreferences prefs = getPreferences(MODE_PRIVATE);
        String id = prefs.getString("admin_device_id", "");
        if (id.isEmpty()) {
            id = UUID.randomUUID().toString().replace("-", "");
            prefs.edit().putString("admin_device_id", id).apply();
        }
        return id;
    }

    private String b64Url(byte[] bytes) {
        return Base64.encodeToString(bytes, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }

    private String publicKeyEncoded(KeyPair pair) {
        return b64Url(pair.getPublic().getEncoded());
    }

    private String signChallenge(String challenge) throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        PrivateKey privateKey = (PrivateKey) store.getKey(ADMIN_KEY_ALIAS, null);
        byte[] nonce = Base64.decode(challenge, Base64.URL_SAFE | Base64.NO_WRAP);
        Signature signer = Signature.getInstance("SHA256withRSA");
        signer.initSign(privateKey);
        signer.update(nonce);
        return b64Url(signer.sign());
    }

    private void autoDeviceLogin() {
        try {
            server = trimServer(server);
            JSONObject body = new JSONObject();
            body.put("device_id", deviceId());
            requestAsync("POST", "/v1/admin/device/challenge", body, false, challengeResult -> {
                if (challengeResult == null) {
                    showLogin();
                    return;
                }
                try {
                    String challenge = challengeResult.getString("challenge");
                    String signature = signChallenge(challenge);
                    JSONObject login = new JSONObject();
                    login.put("device_id", deviceId());
                    login.put("challenge", challenge);
                    login.put("signature", signature);
                    requestAsync("POST", "/v1/admin/device/login", login, false, result -> {
                        if (result == null) {
                            showLogin();
                            return;
                        }
                        adminToken = result.optString("token", "");
                        if (adminToken.isEmpty()) { showLogin(); return; }
                        getPreferences(MODE_PRIVATE).edit()
                            .putString("server", server)
                            .putString("admin_token", adminToken).apply();
                        showConnecting("本机授权验证成功，正在读取云端账号库…");
                        loadUsers("");
                    });
                } catch (Exception e) {
                    toast("本机安全密钥验证失败，请重新绑定");
                    showLogin();
                }
            });
        } catch (Exception e) {
            toast("无法读取本机安全密钥，请重新绑定");
            showLogin();
        }
    }

    private void doAdminLogin() {
        server = DEFAULT_SERVER;
        String password = passwordInput.getText().toString();
        if (password.isEmpty()) { toast("请输入管理员密码"); return; }
        loginButton.setEnabled(false);
        loginButton.setText("正在验证…");
        JSONObject body = new JSONObject();
        try { body.put("username", "admin"); body.put("password", password); } catch (Exception ignored) { }
        requestAsync("POST", "/v1/admin/login", body, false, result -> {
            loginButton.setEnabled(true);
            loginButton.setText("登录本机管理员");
            if (result == null || result.optString("token", "").isEmpty()) {
                loginStatus.setText("管理员密码验证失败，请检查密码或确认本机服务器正在运行。");
                return;
            }
            adminToken = result.optString("token");
            getPreferences(MODE_PRIVATE).edit().putString("admin_token", adminToken).apply();
            passwordInput.setText("");
            showConnecting("管理员身份验证成功，正在读取本地账号…");
            loadUsers("");
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
                if (!"http".equalsIgnoreCase(url.getProtocol()) ||
                    !("127.0.0.1".equals(url.getHost()) || "localhost".equalsIgnoreCase(url.getHost()))) {
                    throw new java.io.IOException("管理版仅连接管理员手机本机账号服务器");
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

    private void loadUsers(String query) { loadUsers(query, 0); }

    private void loadUsers(String query, int attempt) {
        String encoded;
        try { encoded = URLEncoder.encode(query == null ? "" : query, "UTF-8"); }
        catch (Exception e) { encoded = ""; }
        requestAsync("GET", "/v1/admin/users?q=" + encoded, null, true, result -> {
            if (result == null) {
                if (adminToken.isEmpty()) { showLogin(); return; }
                if (attempt < 4) {
                    toast("本机账号服务器正在启动，正在重试连接（" + (attempt + 1) + "/4）");
                    new android.os.Handler(getMainLooper()).postDelayed(() -> loadUsers(query, attempt + 1), 1500);
                } else {
                    toast("本机账号列表读取失败，请确认服务器开关已开启且手机网络正常。");
                }
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
        addLocalAccountServerPanel(page);
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
        boolean permanent = PERMANENT_BAN_UNTIL.equals(until);
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
            TextView ban = text(permanent ? "永久封禁" : "封禁至 " + until, 10, true);
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
        Button permanentButton = button("永久封禁");
        Button unbanButton = button("解禁");
        unbanButton.setEnabled(banned);
        permanentButton.setEnabled(!permanent);

        LinearLayout.LayoutParams actionParams = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, dp(42)
        );
        actionParams.leftMargin = dp(3);
        actionParams.rightMargin = dp(3);
        actions.addView(banButton, actionParams);
        actions.addView(permanentButton, actionParams);
        actions.addView(unbanButton, actionParams);
        row.addView(actions, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        row.setOnClickListener(v -> showUserDetails(user));
        banButton.setOnClickListener(v -> chooseBan(id));
        permanentButton.setOnClickListener(v -> permanentlyBan(id));
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
        AlertDialog.Builder dialog = new AlertDialog.Builder(this).setTitle("账号个人信息")
                .setMessage(message)
                .setPositiveButton("OK", null);
        if (PERMANENT_BAN_UNTIL.equals(user.optString("banned_until", ""))) {
            dialog.setNeutralButton("删除账号", (d, which) -> confirmDeleteAccount(user));
        }
        dialog.show();
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
                            toast("封禁记录已保存；账号下次请求账号状态时将被拒绝");
                            updateVisibleUser(result.optJSONObject("user"));
                        }
                    });
                }).show();
    }

    private void permanentlyBan(String id) {
        EditText reason = new EditText(this);
        reason.setHint("填写永久封禁原因（必填）");
        reason.setMinLines(2);
        reason.setGravity(Gravity.TOP);
        new AlertDialog.Builder(this).setTitle("永久封禁账号")
                .setMessage("永久封禁后，该账号无法登录。只有管理员之后手动删除账号，名字、QQ号和微信号才会释放。")
                .setView(reason)
                .setNegativeButton("取消", null)
                .setPositiveButton("确认永久封禁", (dialog, which) -> {
                    String why = reason.getText().toString().trim();
                    if (why.isEmpty()) { toast("请填写永久封禁原因"); return; }
                    JSONObject body = new JSONObject();
                    try {
                        body.put("banned_until", PERMANENT_BAN_UNTIL);
                        body.put("reason", why);
                    } catch (Exception ignored) {}
                    requestAsync("POST", "/v1/admin/users/" + id + "/ban", body, true, result -> {
                        if (result != null) {
                            toast("账号已永久封禁；如需释放注册信息，请打开账号详情并选择删除账号");
                            updateVisibleUser(result.optJSONObject("user"));
                        }
                    });
                }).show();
    }

    private void confirmDeleteAccount(JSONObject user) {
        String id = user.optString("id");
        new AlertDialog.Builder(this).setTitle("永久删除账号")
                .setMessage("确定删除账号“" + user.optString("name") + "”吗？删除后该账号将无法恢复，原名字、QQ号和微信号会释放，之后可以重新注册。")
                .setNegativeButton("取消", null)
                .setPositiveButton("确认删除并释放资料", (dialog, which) -> {
                    requestAsync("DELETE", "/v1/admin/users/" + id, null, true, result -> {
                        if (result != null && result.optBoolean("deleted", false)) {
                            toast("账号已从云端数据库删除，名字、QQ号和微信号已释放，可以重新注册");
                            loadUsers(searchInput == null ? "" : searchInput.getText().toString());
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
                            toast("已解禁；云端账号状态已更新");
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
