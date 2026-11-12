package com.qianqian.effectcraftadmin;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

/**
 * Exercises the real LanAccountServer routes against the Android SQLiteOpenHelper
 * database under Robolectric. No mock of register/login/ban policy is used.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 35)
public final class LanAccountServerAccountFlowTest {
    private static final String ADMIN_PASSWORD = "qw123456eras";
    private static final String PHOTO_AVATAR = "data:image/jpeg;base64,/9j/";

    private Context context;
    private LanAccountServer server;
    private String adminToken;

    @Before
    public void setUp() throws Exception {
        context = RuntimeEnvironment.getApplication();
        context.deleteDatabase("effectcraft-home-accounts.db");
        context.getSharedPreferences("effectcraft_lan_server", Context.MODE_PRIVATE)
            .edit().clear().commit();

        assertTrue("owner-selected admin password should be accepted for an empty DB",
            LanAccountServer.adoptAdminPasswordIfNoRegisteredUsers(context, ADMIN_PASSWORD));

        server = new LanAccountServer(context);
        JSONObject adminLogin = call("POST", "/v1/admin/login", "", json(
            "username", "admin",
            "password", ADMIN_PASSWORD
        ));
        assertEquals("admin login", 200, status(adminLogin));
        adminToken = body(adminLogin).getString("token");
        assertFalse(adminToken.isEmpty());
    }

    @Test
    public void qqRegistrationLoginBanAndUnbanUseTheSameSqliteAuthority() throws Exception {
        JSONObject registration = call("POST", "/v1/register", "", json(
            "qq", "1939023875",
            "wechat", "",
            "name", "Account Flow Test",
            "password", "account-test-pass",
            "avatar_url", PHOTO_AVATAR
        ));
        assertEquals("QQ-only registration", 200, status(registration));

        JSONObject registeredBody = body(registration);
        String userToken = registeredBody.getString("token");
        JSONObject registeredUser = registeredBody.getJSONObject("user");
        String userId = registeredUser.getString("id");
        assertFalse(userToken.isEmpty());
        assertEquals("1939023875", registeredUser.getString("qq"));
        assertEquals("", registeredUser.getString("wechat"));
        assertEquals(PHOTO_AVATAR, registeredUser.getString("avatar_url"));

        assertFalse("admin password must not be silently replaced after an account exists",
            LanAccountServer.adoptAdminPasswordIfNoRegisteredUsers(context, "another-admin-pass"));
        JSONObject stillValidAdmin = call("POST", "/v1/admin/login", "", json(
            "username", "admin",
            "password", ADMIN_PASSWORD
        ));
        assertEquals("existing admin credential remains valid", 200, status(stillValidAdmin));

        JSONObject login = call("POST", "/v1/login", "", json(
            "identifier", "1939023875",
            "password", "account-test-pass"
        ));
        assertEquals("QQ login", 200, status(login));
        assertEquals(userId, body(login).getJSONObject("user").getString("id"));

        JSONObject forbiddenList = call("GET", "/v1/admin/users",
            body(login).getString("token"), new JSONObject());
        assertEquals("user token cannot access admin user list", 401, status(forbiddenList));

        JSONObject list = call("GET", "/v1/admin/users", adminToken, new JSONObject());
        assertEquals(200, status(list));
        JSONArray users = body(list).getJSONArray("users");
        assertEquals(1, users.length());
        assertEquals(userId, users.getJSONObject(0).getString("id"));

        String banUntil = Instant.now().plus(1, ChronoUnit.HOURS).toString();
        JSONObject ban = call("POST", "/v1/admin/users/" + userId + "/ban", adminToken, json(
            "banned_until", banUntil,
            "reason", "automated account-flow test"
        ));
        assertEquals("admin ban route", 200, status(ban));
        assertEquals(banUntil, body(ban).getJSONObject("user").getString("banned_until"));

        JSONObject bannedLogin = call("POST", "/v1/login", "", json(
            "identifier", "1939023875",
            "password", "account-test-pass"
        ));
        assertEquals("banned user must not log in", 423, status(bannedLogin));
        assertEquals("banned", body(bannedLogin).getJSONObject("detail").getString("code"));

        JSONObject bannedMe = call("GET", "/v1/me", userToken, new JSONObject());
        assertEquals("existing token must be checked against SQLite ban state", 423, status(bannedMe));

        JSONObject bannedProfile = call("POST", "/v1/profile", userToken, json(
            "qq", "1939023875",
            "wechat", "",
            "name", "Changed while banned",
            "avatar_url", PHOTO_AVATAR,
            "current_password", "",
            "new_password", ""
        ));
        assertEquals("banned users cannot update profile", 423, status(bannedProfile));

        JSONObject unban = call("POST", "/v1/admin/users/" + userId + "/ban", adminToken, json(
            "banned_until", JSONObject.NULL,
            "reason", ""
        ));
        assertEquals("admin unban route", 200, status(unban));
        assertTrue(body(unban).getJSONObject("user").isNull("banned_until"));

        JSONObject relogin = call("POST", "/v1/login", "", json(
            "identifier", "1939023875",
            "password", "account-test-pass"
        ));
        assertEquals("unbanned account can log in again", 200, status(relogin));
        assertEquals(userId, body(relogin).getJSONObject("user").getString("id"));

        JSONObject profile = call("POST", "/v1/profile", userToken, json(
            "qq", "1939023875",
            "wechat", "",
            "name", "Profile Updated",
            "avatar_url", PHOTO_AVATAR,
            "current_password", "",
            "new_password", ""
        ));
        assertEquals("profile update after unban", 200, status(profile));
        assertEquals("Profile Updated", body(profile).getJSONObject("user").getString("name"));
    }

    @Test
    public void wechatOnlyRegistrationAndLoginAreSupported() throws Exception {
        JSONObject registration = call("POST", "/v1/register", "", json(
            "qq", "",
            "wechat", "wechat_abc123",
            "name", "WeChat Only",
            "password", "wechat-test-pass",
            "avatar_url", ""
        ));
        assertEquals(200, status(registration));
        JSONObject user = body(registration).getJSONObject("user");
        assertEquals("", user.getString("qq"));
        assertEquals("wechat_abc123", user.getString("wechat"));

        JSONObject login = call("POST", "/v1/login", "", json(
            "identifier", "wechat_abc123",
            "password", "wechat-test-pass"
        ));
        assertEquals(200, status(login));
        assertEquals(user.getString("id"), body(login).getJSONObject("user").getString("id"));
    }

    @Test
    public void duplicateIdentifiersAndBadPasswordsAreRejected() throws Exception {
        JSONObject first = call("POST", "/v1/register", "", json(
            "qq", "123456789",
            "wechat", "",
            "name", "First",
            "password", "duplicate-test-pass",
            "avatar_url", ""
        ));
        assertEquals(200, status(first));

        JSONObject duplicate = call("POST", "/v1/register", "", json(
            "qq", "123456789",
            "wechat", "",
            "name", "Duplicate",
            "password", "duplicate-test-pass",
            "avatar_url", ""
        ));
        assertEquals(409, status(duplicate));

        JSONObject badPassword = call("POST", "/v1/login", "", json(
            "identifier", "123456789",
            "password", "wrong-password"
        ));
        assertEquals(401, status(badPassword));
    }

    private JSONObject call(String method, String path, String token, JSONObject requestBody) throws Exception {
        JSONObject packet = new JSONObject();
        packet.put("method", method);
        packet.put("path", path);
        packet.put("token", token);
        packet.put("body", requestBody.toString());
        JSONObject envelope = server.handleP2PRequest(packet.toString());
        assertNotNull(envelope);
        return envelope;
    }

    private static int status(JSONObject envelope) {
        return envelope.optInt("status", 0);
    }

    private static JSONObject body(JSONObject envelope) throws Exception {
        return new JSONObject(envelope.optString("body", "{}"));
    }

    private static JSONObject json(Object... pairs) throws Exception {
        JSONObject object = new JSONObject();
        for (int i = 0; i < pairs.length; i += 2) object.put(String.valueOf(pairs[i]), pairs[i + 1]);
        return object;
    }
}
