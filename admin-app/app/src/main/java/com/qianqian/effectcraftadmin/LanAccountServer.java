package com.qianqian.effectcraftadmin;

import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.SQLException;
import java.time.Instant;
import java.util.Base64;
import java.util.Collections;
import java.util.Enumeration;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

import javax.crypto.Mac;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * Phone-hosted account API. The listener binds only to the active Wi-Fi IPv4
 * address and accepts peers from that same Wi-Fi subnet (plus localhost).
 * No desktop computer, Docker daemon, or public server is required.
 */
final class LanAccountServer implements Runnable {
    static final int PORT = 8787;
    private static final String PREFS = "effectcraft_lan_server";
    private static final int PBKDF2_ROUNDS = 310000;
    private static final int MAX_BODY = 1024 * 1024;
    private static final Pattern QQ = Pattern.compile("[1-9][0-9]{4,11}");
    private static final Pattern WECHAT = Pattern.compile("[A-Za-z][A-Za-z0-9_-]{5,31}");

    private final Context context;
    private final AccountDb db;
    private final ExecutorService clients = Executors.newFixedThreadPool(8);
    private volatile boolean running = true;
    private volatile ServerSocket listener;
    private volatile String boundIp = "";

    LanAccountServer(Context context) {
        this.context = context.getApplicationContext();
        this.db = new AccountDb(this.context);
        ensureServerSecrets(this.context);
    }

    static String getWifiIpv4() {
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            if (interfaces == null) return "";
            for (NetworkInterface ni : Collections.list(interfaces)) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                String name = ni.getName().toLowerCase(Locale.ROOT);
                if (!name.startsWith("wlan") && !name.contains("wifi")) continue;
                for (java.net.InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    InetAddress address = ia.getAddress();
                    if (address instanceof Inet4Address && address.isSiteLocalAddress()) {
                        return address.getHostAddress();
                    }
                }
            }
        } catch (Exception ignored) { }
        return "";
    }

    static String ensureAdminPassword(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (p.contains("admin_hash")) return p.getString("admin_initial_password_pending", null);
        String password = randomPassword();
        byte[] salt = randomBytes(16);
        String hash = hashPassword(password, salt);
        p.edit()
            .putString("admin_salt", b64(salt))
            .putString("admin_hash", hash)
            .putString("jwt_secret", b64(randomBytes(48)))
            .putString("admin_initial_password_pending", password)
            .apply();
        return password;
    }

    static void acknowledgeAdminPasswordSaved(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().remove("admin_initial_password_pending").apply();
    }

    private static void ensureServerSecrets(Context context) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (!p.contains("jwt_secret")) {
            p.edit().putString("jwt_secret", b64(randomBytes(48))).apply();
        }
        if (!p.contains("admin_hash")) {
            ensureAdminPassword(context);
        }
    }

    private static String randomPassword() {
        String raw = b64(randomBytes(18)).replace("-", "A").replace("_", "B");
        return "EC-" + raw.substring(0, Math.min(22, raw.length())) + "9!";
    }

    private static byte[] randomBytes(int length) {
        byte[] bytes = new byte[length];
        new SecureRandom().nextBytes(bytes);
        return bytes;
    }

    private static String b64(byte[] bytes) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static byte[] unb64(String value) {
        return Base64.getUrlDecoder().decode(value);
    }

    @Override public void run() {
        // The account HTTP endpoint is only a loopback bridge for the manager UI.
        // Remote users must use the authenticated libp2p request-response channel.
        // Binding localhost also lets the manager operate over mobile data without Wi-Fi.
        while (running) {
            try (ServerSocket server = new ServerSocket()) {
                server.setReuseAddress(true);
                server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), PORT), 16);
                server.setSoTimeout(2500);
                listener = server;
                boundIp = "127.0.0.1";
                while (running) {
                    try {
                        Socket socket = server.accept();
                        clients.execute(() -> handleClient(socket, "127.0.0.1"));
                    } catch (SocketTimeoutException ignored) {
                        // Keep the loop responsive to stopServer().
                    }
                }
            } catch (Exception e) {
                boundIp = "";
                sleepQuietly(2500);
            } finally {
                listener = null;
                boundIp = "";
            }
        }
        clients.shutdownNow();
    }

    void stopServer() {
        running = false;
        ServerSocket current = listener;
        if (current != null) {
            try { current.close(); } catch (IOException ignored) { }
        }
    }

    String getBoundIp() {
        return boundIp;
    }

    private static void sleepQuietly(long millis) {
        try { Thread.sleep(millis); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    private void handleClient(Socket socket, String serverIp) {
        try (Socket client = socket) {
            client.setSoTimeout(10000);
            InetAddress peer = ((InetSocketAddress) client.getRemoteSocketAddress()).getAddress();
            if (!isAllowedPeer(peer, serverIp)) {
                writeResponse(client, 403, jsonError("只允许连接同一家庭 Wi-Fi 的设备访问"));
                return;
            }
            BufferedInputStream in = new BufferedInputStream(client.getInputStream());
            String requestLine = readLine(in);
            if (requestLine == null || requestLine.isEmpty()) return;
            String[] first = requestLine.split(" ");
            if (first.length < 2) {
                writeResponse(client, 400, jsonError("请求格式不正确"));
                return;
            }
            String method = first[0].toUpperCase(Locale.ROOT);
            String target = first[1];
            java.util.Map<String, String> headers = new java.util.HashMap<>();
            String line;
            while ((line = readLine(in)) != null && !line.isEmpty()) {
                int colon = line.indexOf(':');
                if (colon > 0) headers.put(line.substring(0, colon).trim().toLowerCase(Locale.ROOT), line.substring(colon + 1).trim());
            }
            int length = 0;
            try { length = Integer.parseInt(headers.getOrDefault("content-length", "0")); }
            catch (NumberFormatException ignored) { }
            if (length < 0 || length > MAX_BODY) {
                writeResponse(client, 413, jsonError("请求内容过大"));
                return;
            }
            byte[] bodyBytes = readExact(in, length);
            JSONObject body = bodyBytes.length == 0 ? new JSONObject() : new JSONObject(new String(bodyBytes, StandardCharsets.UTF_8));
            JSONObject result = route(method, target, headers, body);
            int status = result.optInt("_status", 200);
            result.remove("_status");
            writeResponse(client, status, result);
        } catch (SecurityException authError) {
            // Return a real 401 so the Android admin UI can clear an expired
            // token and present the login form instead of remaining blank.
            String message = authError.getMessage();
            try { writeResponse(socket, 401, jsonError(message == null ? "需要重新登录" : message)); }
            catch (Exception ignoredAgain) { }
        } catch (Exception requestError) {
            String message = requestError.getMessage();
            try { writeResponse(socket, 400, jsonError(message == null ? "请求无法处理，请检查输入后重试" : message)); }
            catch (Exception ignoredAgain) { }
        }
    }

    private static boolean isAllowedPeer(InetAddress peer, String serverIp) {
        if (peer.isLoopbackAddress()) return true;
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            if (interfaces == null) return false;
            for (NetworkInterface ni : Collections.list(interfaces)) {
                for (java.net.InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    if (!serverIp.equals(ia.getAddress().getHostAddress())) continue;
                    if (ia.getAddress() instanceof Inet4Address && peer instanceof Inet4Address) {
                        int prefix = ia.getNetworkPrefixLength();
                        byte[] local = ia.getAddress().getAddress();
                        byte[] remote = peer.getAddress();
                        int fullBytes = prefix / 8;
                        int remainingBits = prefix % 8;
                        for (int i = 0; i < fullBytes; i++) if (local[i] != remote[i]) return false;
                        if (remainingBits > 0) {
                            int mask = 0xff << (8 - remainingBits);
                            if ((local[fullBytes] & mask) != (remote[fullBytes] & mask)) return false;
                        }
                        return true;
                    }
                }
            }
        } catch (Exception ignored) { }
        return false;
    }

    private static String readLine(BufferedInputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        int value;
        boolean cr = false;
        while ((value = in.read()) != -1) {
            if (cr && value == '\n') break;
            if (cr) out.write('\r');
            cr = value == '\r';
            if (!cr) out.write(value);
            if (out.size() > 8192) throw new IOException("Header too long");
        }
        if (value == -1 && out.size() == 0) return null;
        return out.toString("ISO-8859-1");
    }

    private static byte[] readExact(BufferedInputStream in, int length) throws IOException {
        byte[] bytes = new byte[length];
        int offset = 0;
        while (offset < length) {
            int n = in.read(bytes, offset, length - offset);
            if (n < 0) throw new IOException("Unexpected end of request body");
            offset += n;
        }
        return bytes;
    }

    private static void writeResponse(Socket socket, int status, JSONObject data) throws IOException {
        byte[] body = data.toString().getBytes(StandardCharsets.UTF_8);
        String reason = status == 200 ? "OK" : status == 201 ? "Created" : status == 400 ? "Bad Request" :
            status == 401 ? "Unauthorized" : status == 403 ? "Forbidden" : status == 404 ? "Not Found" :
            status == 409 ? "Conflict" : status == 413 ? "Payload Too Large" : status == 422 ? "Unprocessable Entity" :
            status == 423 ? "Locked" : status == 429 ? "Too Many Requests" : "Internal Server Error";
        String headers = "HTTP/1.1 " + status + " " + reason + "\r\n" +
            "Content-Type: application/json; charset=utf-8\r\n" +
            "Content-Length: " + body.length + "\r\n" +
            "Cache-Control: no-store\r\nConnection: close\r\n\r\n";
        socket.getOutputStream().write(headers.getBytes(StandardCharsets.ISO_8859_1));
        socket.getOutputStream().write(body);
        socket.getOutputStream().flush();
    }

    JSONObject handleP2PRequest(String wire) {
        try {
            JSONObject packet = new JSONObject(wire);
            String method = packet.optString("method", "GET").toUpperCase(Locale.ROOT);
            String path = packet.optString("path", "");
            String token = packet.optString("token", "");
            String bodyText = packet.optString("body", "");
            java.util.Map<String, String> headers = new java.util.HashMap<>();
            if (!token.isEmpty()) headers.put("authorization", "Bearer " + token);
            JSONObject body = bodyText.isEmpty() ? new JSONObject() : new JSONObject(bodyText);
            JSONObject result = route(method, path, headers, body);
            int status = result.optInt("_status", 200);
            result.remove("_status");
            JSONObject envelope = new JSONObject();
            envelope.put("status", status);
            envelope.put("body", result.toString());
            return envelope;
        } catch (SecurityException error) {
            try {
                JSONObject envelope = new JSONObject();
                JSONObject detail = new JSONObject(); detail.put("detail", error.getMessage() == null ? "需要登录" : error.getMessage());
                envelope.put("status", 401); envelope.put("body", detail.toString());
                return envelope;
            } catch (Exception ignored) { return new JSONObject(); }
        } catch (Exception error) {
            try {
                JSONObject envelope = new JSONObject();
                JSONObject detail = new JSONObject(); detail.put("detail", error.getMessage() == null ? "账号请求无法处理" : error.getMessage());
                envelope.put("status", 400); envelope.put("body", detail.toString());
                return envelope;
            } catch (Exception ignored) { return new JSONObject(); }
        }
    }

    private JSONObject route(String method, String target, java.util.Map<String, String> headers, JSONObject body) throws Exception {
        String path = target.split("\\?", 2)[0];
        String query = target.contains("?") ? target.substring(target.indexOf('?') + 1) : "";
        if (method.equals("GET") && path.equals("/health")) {
            // Opening the database here forces SQLiteOpenHelper to create/upgrade
            // the schema before the Activity enables administrator login.
            try (Cursor check = db.getReadableDatabase().rawQuery("PRAGMA quick_check", null)) {
                if (!check.moveToFirst() || !"ok".equalsIgnoreCase(check.getString(0))) {
                    return error(503, "本机 SQLite 数据库完整性检查未通过", "", "");
                }
            }
            SharedPreferences secrets = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            if (secrets.getString("admin_salt", "").isEmpty()
                || secrets.getString("admin_hash", "").isEmpty()
                || secrets.getString("jwt_secret", "").isEmpty()) {
                return error(503, "本机管理员凭据尚未初始化", "", "");
            }
            JSONObject ok = new JSONObject();
            ok.put("ok", true);
            ok.put("ready", true);
            ok.put("database", "ready");
            ok.put("service", "EffectCraft Android Home Account Server");
            return ok;
        }
        if (method.equals("POST") && path.equals("/v1/register")) return register(body);
        if (method.equals("POST") && path.equals("/v1/login")) return login(body);
        if (method.equals("POST") && path.equals("/v1/admin/login")) return adminLogin(body);
        if (method.equals("GET") && path.equals("/v1/me")) {
            JSONObject claims = authorize(headers, "user");
            JSONObject user = findUser(claims.getString("sub"));
            if (isBanned(user)) return error(423, "账号已被封禁", user.optString("banned_until"), user.optString("ban_reason"));
            JSONObject out = new JSONObject(); out.put("user", user); return out;
        }
        if (method.equals("POST") && path.equals("/v1/profile")) return updateProfile(headers, body);
        if (path.equals("/v1/admin/users") && method.equals("GET")) {
            authorize(headers, "admin");
            String q = queryValue(query, "q").toLowerCase(Locale.ROOT);
            return listUsers(q);
        }
        if (path.startsWith("/v1/admin/users/")) {
            authorize(headers, "admin");
            String tail = path.substring("/v1/admin/users/".length());
            if (method.equals("GET")) {
                JSONObject out = new JSONObject(); out.put("user", findUser(tail)); return out;
            }
            if (method.equals("POST") && tail.endsWith("/ban")) {
                String id = tail.substring(0, tail.length() - 4);
                return banUser(id, body);
            }
        }
        return error(404, "未找到请求接口", "", "");
    }

    private JSONObject register(JSONObject body) throws Exception {
        String qq = body.optString("qq", "").trim();
        String wechat = body.optString("wechat", "").trim().toLowerCase(Locale.ROOT);
        String name = body.optString("name", "").trim();
        String password = body.optString("password", "");
        String avatar = body.optString("avatar_url", "").trim();
        if (qq.isEmpty() && wechat.isEmpty()) return error(422, "QQ号和微信号至少填写一项", "", "");
        if (!qq.isEmpty() && !QQ.matcher(qq).matches()) return error(422, "QQ号应填写5至12位数字", "", "");
        if (!wechat.isEmpty() && !WECHAT.matcher(body.optString("wechat", "").trim()).matches()) return error(422, "微信号格式不正确", "", "");
        if (name.isEmpty() || name.length() > 40) return error(422, "姓名不能为空且不能超过40字", "", "");
        if (password.length() < 8 || password.length() > 128) return error(422, "密码至少8位", "", "");
        if (!avatar.isEmpty() && !(avatar.startsWith("https://") || avatar.startsWith("http://"))) return error(422, "头像地址格式不正确", "", "");
        String id = UUID.randomUUID().toString();
        byte[] salt = randomBytes(16);
        String passHash = hashPassword(password, salt);
        SQLiteDatabase writable = db.getWritableDatabase();
        try {
            android.content.ContentValues values = new android.content.ContentValues();
            values.put("id", id);
            if (qq.isEmpty()) values.putNull("qq"); else values.put("qq", qq);
            if (wechat.isEmpty()) values.putNull("wechat"); else values.put("wechat", wechat);
            values.put("name", name); values.put("password_hash", passHash);
            values.put("password_salt", b64(salt)); values.put("avatar_url", avatar);
            values.put("created_at", Instant.now().toString());
            writable.insertOrThrow("accounts", null, values);
        } catch (android.database.SQLException e) {
            return error(409, "QQ号或微信号已注册", "", "");
        }
        return authResult(id, "user", 30L * 24 * 60 * 60);
    }

    private JSONObject login(JSONObject body) throws Exception {
        String id = body.optString("identifier", "").trim();
        String password = body.optString("password", "");
        Cursor c = db.getReadableDatabase().query("accounts", null, "qq=? OR wechat=?", new String[]{id, id.toLowerCase(Locale.ROOT)}, null, null, null, "1");
        try {
            if (!c.moveToFirst()) return error(401, "QQ号/微信号或密码错误", "", "");
            String userId = c.getString(c.getColumnIndexOrThrow("id"));
            if (!verifyPassword(password, c.getString(c.getColumnIndexOrThrow("password_salt")), c.getString(c.getColumnIndexOrThrow("password_hash")))) {
                return error(401, "QQ号/微信号或密码错误", "", "");
            }
            JSONObject user = userFromCursor(c);
            if (isBanned(user)) return error(423, "账号已被封禁", user.optString("banned_until"), user.optString("ban_reason"));
            return authResult(userId, "user", 30L * 24 * 60 * 60);
        } finally { c.close(); }
    }

    private JSONObject adminLogin(JSONObject body) throws Exception {
        String username = body.optString("username", "");
        if (!"admin".equals(username) || !verifyAdminPassword(body.optString("password", ""))) {
            return error(401, "管理员账号或密码错误", "", "");
        }
        JSONObject out = new JSONObject();
        out.put("token", token("admin", "admin", 8L * 60 * 60));
        out.put("expires_in", 8L * 60 * 60);
        return out;
    }

    private JSONObject updateProfile(java.util.Map<String, String> headers, JSONObject body) throws Exception {
        JSONObject claims = authorize(headers, "user");
        String id = claims.getString("sub");
        JSONObject current = findUser(id);
        if (isBanned(current)) return error(423, "账号已被封禁", current.optString("banned_until"), current.optString("ban_reason"));
        String qq = body.optString("qq", "").trim();
        String wechatRaw = body.optString("wechat", "").trim();
        String wechat = wechatRaw.toLowerCase(Locale.ROOT);
        String name = body.optString("name", "").trim();
        String avatar = body.optString("avatar_url", "").trim();
        if ((qq.isEmpty() && wechatRaw.isEmpty()) || (!qq.isEmpty() && !QQ.matcher(qq).matches()) || (!wechatRaw.isEmpty() && !WECHAT.matcher(wechatRaw).matches()) || name.isEmpty()) return error(422, "QQ号和微信号至少填写一项，且已填写的账号格式必须正确", "", "");
        String newPassword = body.optString("new_password", "");
        android.content.ContentValues values = new android.content.ContentValues();
        if (qq.isEmpty()) values.putNull("qq"); else values.put("qq", qq);
        if (wechat.isEmpty()) values.putNull("wechat"); else values.put("wechat", wechat);
        values.put("name", name); values.put("avatar_url", avatar);
        if (!newPassword.isEmpty()) {
            Cursor c = db.getReadableDatabase().query("accounts", new String[]{"password_hash", "password_salt"}, "id=?", new String[]{id}, null, null, null);
            try {
                if (!c.moveToFirst() || !verifyPassword(body.optString("current_password", ""), c.getString(1), c.getString(0))) return error(401, "当前密码不正确", "", "");
            } finally { c.close(); }
            if (newPassword.length() < 8) return error(422, "新密码至少8位", "", "");
            byte[] salt = randomBytes(16);
            values.put("password_salt", b64(salt)); values.put("password_hash", hashPassword(newPassword, salt));
        }
        try {
            db.getWritableDatabase().update("accounts", values, "id=?", new String[]{id});
        } catch (android.database.SQLException e) {
            return error(409, "QQ号或微信号已被其他账号使用", "", "");
        }
        JSONObject out = new JSONObject(); out.put("user", findUser(id)); return out;
    }

    private JSONObject listUsers(String query) throws Exception {
        JSONArray users = new JSONArray();
        Cursor c;
        if (query.isEmpty()) c = db.getReadableDatabase().query("accounts", null, null, null, null, null, "created_at DESC", "500");
        else c = db.getReadableDatabase().query("accounts", null, "qq LIKE ? OR wechat LIKE ? OR name LIKE ?",
            new String[]{"%" + query + "%", "%" + query + "%", "%" + query + "%"}, null, null, "created_at DESC", "500");
        try { while (c.moveToNext()) users.put(userFromCursor(c)); } finally { c.close(); }
        JSONObject out = new JSONObject(); out.put("users", users); return out;
    }

    private JSONObject banUser(String id, JSONObject body) throws Exception {
        JSONObject user = findUser(id);
        Object untilValue = body.opt("banned_until");
        android.content.ContentValues values = new android.content.ContentValues();
        if (untilValue == null || untilValue == JSONObject.NULL) {
            values.putNull("banned_until"); values.put("ban_reason", "");
        } else {
            String until = String.valueOf(untilValue);
            try { if (!Instant.parse(until).isAfter(Instant.now())) return error(422, "封禁时间必须晚于当前时间", "", ""); }
            catch (Exception e) { return error(422, "封禁时间格式不正确", "", ""); }
            String reason = body.optString("reason", "").trim();
            if (reason.isEmpty()) return error(422, "请填写封禁原因", "", "");
            values.put("banned_until", until); values.put("ban_reason", reason);
        }
        db.getWritableDatabase().update("accounts", values, "id=?", new String[]{id});
        JSONObject out = new JSONObject(); out.put("user", findUser(id)); return out;
    }

    private JSONObject findUser(String id) throws Exception {
        Cursor c = db.getReadableDatabase().query("accounts", null, "id=?", new String[]{id}, null, null, null, "1");
        try {
            if (!c.moveToFirst()) throw new IllegalArgumentException("账号不存在");
            return userFromCursor(c);
        } finally { c.close(); }
    }

    private static JSONObject userFromCursor(Cursor c) throws Exception {
        JSONObject u = new JSONObject();
        u.put("id", c.getString(c.getColumnIndexOrThrow("id")));
        int qqColumn = c.getColumnIndexOrThrow("qq");
        int wechatColumn = c.getColumnIndexOrThrow("wechat");
        u.put("qq", c.isNull(qqColumn) ? "" : c.getString(qqColumn));
        u.put("wechat", c.isNull(wechatColumn) ? "" : c.getString(wechatColumn));
        u.put("name", c.getString(c.getColumnIndexOrThrow("name")));
        u.put("avatar_url", c.getString(c.getColumnIndexOrThrow("avatar_url")));
        u.put("created_at", c.getString(c.getColumnIndexOrThrow("created_at")));
        u.put("banned_until", c.isNull(c.getColumnIndexOrThrow("banned_until")) ? JSONObject.NULL : c.getString(c.getColumnIndexOrThrow("banned_until")));
        u.put("ban_reason", c.getString(c.getColumnIndexOrThrow("ban_reason")));
        return u;
    }

    private boolean isBanned(JSONObject user) {
        String until = user.optString("banned_until", "");
        if (until.isEmpty() || "null".equals(until)) return false;
        try { return Instant.parse(until).isAfter(Instant.now()); } catch (Exception e) { return true; }
    }

    private JSONObject authorize(java.util.Map<String, String> headers, String role) throws Exception {
        String auth = headers.getOrDefault("authorization", "");
        if (!auth.startsWith("Bearer ")) throw new SecurityException("需要登录");
        JSONObject claims = readToken(auth.substring(7).trim());
        if (!role.equals(claims.optString("role"))) throw new SecurityException("账号权限不足");
        return claims;
    }

    private JSONObject authResult(String id, String role, long ttl) throws Exception {
        JSONObject out = new JSONObject();
        out.put("token", token(id, role, ttl));
        out.put("user", findUser(id));
        return out;
    }

    private String token(String subject, String role, long ttl) throws Exception {
        long now = System.currentTimeMillis() / 1000L;
        JSONObject header = new JSONObject(); header.put("alg", "HS256"); header.put("typ", "JWT");
        JSONObject payload = new JSONObject(); payload.put("sub", subject); payload.put("role", role); payload.put("iat", now); payload.put("exp", now + ttl);
        String unsigned = b64(header.toString().getBytes(StandardCharsets.UTF_8)) + "." + b64(payload.toString().getBytes(StandardCharsets.UTF_8));
        return unsigned + "." + sign(unsigned);
    }

    private JSONObject readToken(String token) throws Exception {
        String[] parts = token.split("\\.");
        if (parts.length != 3 || !MessageDigest.isEqual(parts[2].getBytes(StandardCharsets.UTF_8), sign(parts[0] + "." + parts[1]).getBytes(StandardCharsets.UTF_8))) {
            throw new SecurityException("登录已失效，请重新登录");
        }
        JSONObject claims = new JSONObject(new String(unb64(parts[1]), StandardCharsets.UTF_8));
        if (claims.optLong("exp", 0) <= System.currentTimeMillis() / 1000L) throw new SecurityException("登录已失效，请重新登录");
        return claims;
    }

    private String sign(String value) throws Exception {
        String secret = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("jwt_secret", "");
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(unb64(secret), "HmacSHA256"));
        return b64(mac.doFinal(value.getBytes(StandardCharsets.UTF_8)));
    }

    private boolean verifyAdminPassword(String candidate) {
        SharedPreferences p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return verifyPassword(candidate, p.getString("admin_salt", ""), p.getString("admin_hash", ""));
    }

    /** Local diagnostic only: checks the entered value against this install's stored verifier.
     * It never changes the password, token secret, or SQLite account database.
     */
    static boolean verifyAdminPasswordOnDevice(Context context, String candidate) {
        SharedPreferences p = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return verifyPassword(candidate, p.getString("admin_salt", ""), p.getString("admin_hash", ""));
    }

    /**
     * One-time owner-selected password adoption for a demonstrably empty local
     * account database. This stores only a salted PBKDF2 verifier, never the
     * candidate plaintext. It does not reset JWT/peer identity or alter SQLite.
     */
    static boolean adoptAdminPasswordIfNoRegisteredUsers(Context context, String candidate) {
        if (candidate == null || candidate.length() < 8 || candidate.length() > 128) return false;
        Context app = context.getApplicationContext();
        if (countRegisteredAccounts(app) != 0) return false;
        byte[] salt = randomBytes(16);
        String hash = hashPassword(candidate, salt);
        SharedPreferences p = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        boolean saved = p.edit()
            .putString("admin_salt", b64(salt))
            .putString("admin_hash", hash)
            .putString("admin_password_version", "owner-selected-empty-db-v1")
            .remove("admin_initial_password_pending")
            .commit();
        return saved && verifyPassword(candidate,
            p.getString("admin_salt", ""), p.getString("admin_hash", ""));
    }

    private static int countRegisteredAccounts(Context context) {
        AccountDb database = null;
        try {
            database = new AccountDb(context.getApplicationContext());
            try (Cursor cursor = database.getReadableDatabase().rawQuery("SELECT COUNT(*) FROM accounts", null)) {
                return cursor.moveToFirst() ? cursor.getInt(0) : -1;
            }
        } catch (Exception error) {
            return -1;
        } finally {
            if (database != null) database.close();
        }
    }

    private static String hashPassword(String password, byte[] salt) {
        try {
            PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, PBKDF2_ROUNDS, 256);
            byte[] hash = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();
            spec.clearPassword();
            return b64(hash);
        } catch (Exception e) { throw new IllegalStateException("密码加密失败", e); }
    }

    private static boolean verifyPassword(String password, String salt, String expected) {
        try {
            if (password == null || salt == null || expected == null || salt.isEmpty() || expected.isEmpty()) return false;
            byte[] actual = unb64(hashPassword(password, unb64(salt)));
            return MessageDigest.isEqual(actual, unb64(expected));
        } catch (Exception e) { return false; }
    }

    private static JSONObject error(int status, String message, String until, String reason) throws Exception {
        JSONObject detail = new JSONObject();
        detail.put("message", message);
        if (status == 423) { detail.put("until", until); detail.put("reason", reason); detail.put("code", "banned"); }
        JSONObject out = new JSONObject(); out.put("detail", detail); out.put("_status", status); return out;
    }

    private static JSONObject jsonError(String message) {
        JSONObject detail = new JSONObject();
        JSONObject out = new JSONObject();
        try { detail.put("message", message); out.put("detail", detail); } catch (Exception ignored) { }
        return out;
    }

    private static String queryValue(String query, String key) {
        for (String part : query.split("&")) {
            String[] pair = part.split("=", 2);
            if (pair.length == 2 && pair[0].equals(key)) {
                try { return URLDecoder.decode(pair[1], "UTF-8"); } catch (Exception ignored) { }
            }
        }
        return "";
    }

    private static final class AccountDb extends SQLiteOpenHelper {
        AccountDb(Context context) { super(context, "effectcraft-home-accounts.db", null, 2); }
        @Override public void onCreate(SQLiteDatabase db) {
            db.execSQL("CREATE TABLE accounts (id TEXT PRIMARY KEY, qq TEXT UNIQUE, wechat TEXT UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, avatar_url TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, banned_until TEXT, ban_reason TEXT NOT NULL DEFAULT '')");
            db.execSQL("CREATE INDEX idx_accounts_name ON accounts(name)");
        }
        @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
            if (oldVersion < 2) {
                db.execSQL("ALTER TABLE accounts RENAME TO accounts_v1");
                db.execSQL("CREATE TABLE accounts (id TEXT PRIMARY KEY, qq TEXT UNIQUE, wechat TEXT UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, avatar_url TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, banned_until TEXT, ban_reason TEXT NOT NULL DEFAULT '')");
                db.execSQL("INSERT INTO accounts(id,qq,wechat,name,password_hash,password_salt,avatar_url,created_at,banned_until,ban_reason) SELECT id,NULLIF(qq,''),NULLIF(wechat,''),name,password_hash,password_salt,avatar_url,created_at,banned_until,ban_reason FROM accounts_v1");
                db.execSQL("DROP TABLE accounts_v1");
                db.execSQL("CREATE INDEX idx_accounts_name ON accounts(name)");
            }
        }
    }
}
