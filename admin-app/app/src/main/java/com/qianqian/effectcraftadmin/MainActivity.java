package com.qianqian.effectcraftadmin;

import android.app.Activity;
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
    private String server = "http://127.0.0.1:8787";
    private String adminToken = "";
    private LinearLayout root;
    private LinearLayout rows;
    private EditText serverInput;
    private EditText usernameInput;
    private EditText passwordInput;
    private EditText searchInput;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(245, 247, 250));
        getWindow().setNavigationBarColor(Color.rgb(245, 247, 250));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        String wifiIp = LanAccountServer.getWifiIpv4();
        server = wifiIp.isEmpty() ? "http://127.0.0.1:8787" : "http://" + wifiIp + ":8787";
        adminToken = getPreferences(MODE_PRIVATE).getString("admin_token", "");
        String firstAdminPassword = LanAccountServer.ensureAdminPassword(this);
        android.content.Intent service = new android.content.Intent(this, LanServerService.class);
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            startForegroundService(service);
        } else {
            startService(service);
        }
        if (!adminToken.isEmpty()) {
            loadUsers("");
        } else {
            showLogin();
        }
        if (firstAdminPassword != null) {
            new AlertDialog.Builder(this)
                .setTitle("首次启动：管理员密码")
                .setMessage("请先保存这次显示的管理员密码。关闭后不会再次显示。\\n\\n管理员账号：admin\\n管理员密码：" + firstAdminPassword + "\\n\\n账号服务只在本机连接家庭 Wi-Fi 时运行。")
                .setCancelable(false)
                .setPositiveButton("我已保存", (dialog, which) -> { })
                .show();
        }
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

    private void showLogin() {
        LinearLayout page = column();
        TextView title = text("EffectCraft 账号管理", 24, true);
        page.addView(title, new LinearLayout.LayoutParams(-1, dp(56)));
        page.addView(text("本机作为账号主机运行，无需电脑。", 14, false));
        String lanIp = LanAccountServer.getWifiIpv4();
        page.addView(text(lanIp.isEmpty()
            ? "尚未检测到 Wi-Fi 地址：请先连接家中 Wi-Fi。"
            : "其他手机在同一 Wi-Fi 下填写：http://" + lanIp + ":8787", 13, true));
        page.addView(text("本机管理员连接地址：" + server, 12, false));
        page.addView(text("服务器地址", 13, true));
        serverInput = field("http://192.168.x.x:8787", false);
        serverInput.setText(server);
        page.addView(serverInput);
        page.addView(text("管理员账号", 13, true));
        usernameInput = field("admin", false);
        usernameInput.setText("admin");
        page.addView(usernameInput);
        page.addView(text("管理员密码", 13, true));
        passwordInput = field("输入安装服务器时设置的管理员密码", true);
        page.addView(passwordInput);
        Button login = button("登录管理后台");
        page.addView(login, new LinearLayout.LayoutParams(-1, dp(52)));
        login.setOnClickListener(v -> doAdminLogin());
        page.addView(text("管理员密码只保存在家中服务器的配置文件中，不会写入普通用户账号资料。", 12, false));
        setRoot(page);
    }

    private void doAdminLogin() {
        server = trimServer(serverInput.getText().toString());
        String user = usernameInput.getText().toString().trim();
        String pass = passwordInput.getText().toString();
        if (server.isEmpty() || user.isEmpty() || pass.isEmpty()) {
            toast("请填写服务器地址、管理员账号和密码");
            return;
        }
        JSONObject body = new JSONObject();
        try { body.put("username", user); body.put("password", pass); } catch (Exception ignored) {}
        requestAsync("POST", "/v1/admin/login", body, false, result -> {
            if (result == null) return;
            try {
                adminToken = result.getString("token");
                getPreferences(MODE_PRIVATE).edit().putString("server", server).putString("admin_token", adminToken).apply();
                loadUsers("");
            } catch (Exception e) { toast("管理员登录返回数据不正确"); }
        });
    }

    private boolean isPrivateLanHost(String host) throws Exception {
        java.net.InetAddress[] addresses = java.net.InetAddress.getAllByName(host);
        for (java.net.InetAddress address : addresses) {
            if (address.isLoopbackAddress() || address.isSiteLocalAddress() || address.isLinkLocalAddress()) {
                return true;
            }
        }
        return false;
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
                if (!isPrivateLanHost(url.getHost())) {
                    throw new java.io.IOException("只允许连接家庭 Wi-Fi 局域网服务器");
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
                JSONObject parsed = new JSONObject(data.toString(StandardCharsets.UTF_8));
                if (code >= 200 && code < 300) result = parsed;
                else {
                    Object detail = parsed.opt("detail");
                    if (detail instanceof JSONObject) error = ((JSONObject) detail).optString("message", detail.toString());
                    else error = detail == null ? ("HTTP " + code) : detail.toString();
                    if (code == 401 || code == 403) {
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
            if (result == null) return;
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
        Button banButton = button(banned ? "解除" : "封禁");
        row.addView(banButton);
        row.setOnClickListener(v -> showUserDetails(user));
        banButton.setOnClickListener(v -> {
            if (banned) unban(id); else chooseBan(id);
        });
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
                            toast("已封禁该账号");
                            loadUsers(searchInput == null ? "" : searchInput.getText().toString());
                        }
                    });
                }).show();
    }

    private void unban(String id) {
        new AlertDialog.Builder(this).setTitle("解除封禁")
                .setMessage("确定解除该账号封禁吗？")
                .setNegativeButton("取消", null)
                .setPositiveButton("解除", (dialog, which) -> {
                    JSONObject body = new JSONObject();
                    try { body.put("banned_until", JSONObject.NULL); body.put("reason", ""); } catch (Exception ignored) {}
                    requestAsync("POST", "/v1/admin/users/" + id + "/ban", body, true, result -> {
                        if (result != null) {
                            toast("已解除封禁");
                            loadUsers(searchInput == null ? "" : searchInput.getText().toString());
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
