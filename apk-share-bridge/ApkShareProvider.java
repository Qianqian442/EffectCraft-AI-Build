package com.artcraft.effectcraft;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Binder;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import android.util.Base64;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Serves the installed EffectCraft APK only to the official QQ client, and only
 * after the signed account-manager app has a currently verified admin session.
 *
 * The APK is never copied to shared storage. A short-lived opaque URI is issued
 * to the manager app and a temporary read grant is given to QQ only.
 */
public final class ApkShareProvider extends ContentProvider {
    private static final String AUTHORITY = "com.artcraft.effectcraft.apkshare";
    private static final String ADMIN_PACKAGE = "com.qianqian.effectcraftadmin";
    private static final String ADMIN_AUTHORITY = "com.qianqian.effectcraftadmin.apkauth";
    private static final String QQ_PACKAGE = "com.tencent.mobileqq";
    private static final String ADMIN_CERT_SHA256 =
        "4a49c53d6d449e2579bceda3c0159639f73e21047fb4b1825ed145159e68db19";
    private static final long URI_TTL_MS = 10L * 60L * 1000L;
    private static final Map<String, Long> grants = new ConcurrentHashMap<>();
    private static final SecureRandom random = new SecureRandom();

    @Override public boolean onCreate() { return true; }

    @Override
    public Bundle call(String method, String arg, Bundle extras) {
        if (!"prepare_qq_apk_share".equals(method)) return super.call(method, arg, extras);
        Context context = getContext();
        if (context == null) throw new SecurityException("EffectCraft sharing provider is unavailable");

        int uid = Binder.getCallingUid();
        if (!uidOwnsPackage(context, uid, ADMIN_PACKAGE)
                || !packageHasCertificate(context, ADMIN_PACKAGE, ADMIN_CERT_SHA256)) {
            throw new SecurityException("Only the signed EffectCraft management app can request APK sharing");
        }

        if (!isAdminSessionVerified(context)) {
            Bundle denied = new Bundle();
            denied.putBoolean("authorized", false);
            denied.putString("message", "管理版管理员会话未验证或已失效");
            return denied;
        }

        if (!packageInstalled(context, QQ_PACKAGE)) {
            Bundle denied = new Bundle();
            denied.putBoolean("authorized", false);
            denied.putString("message", "未检测到手机 QQ");
            return denied;
        }

        String token = newToken();
        grants.put(token, System.currentTimeMillis() + URI_TTL_MS);
        Uri uri = new Uri.Builder()
            .scheme("content")
            .authority(AUTHORITY)
            .appendPath("apk")
            .appendPath(token)
            .build();

        context.grantUriPermission(QQ_PACKAGE, uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        Bundle result = new Bundle();
        result.putBoolean("authorized", true);
        result.putString("uri", uri.toString());
        result.putString("mime_type", "application/vnd.android.package-archive");
        result.putString("display_name", "EffectCraft.apk");
        result.putLong("expires_in_ms", URI_TTL_MS);
        return result;
    }

    private static boolean isAdminSessionVerified(Context context) {
        try {
            Uri authUri = Uri.parse("content://" + ADMIN_AUTHORITY);
            Bundle state = context.getContentResolver().call(
                authUri, "is_apk_share_authorized", null, null
            );
            return state != null && state.getBoolean("authorized", false);
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static String newToken() {
        byte[] bytes = new byte[24];
        random.nextBytes(bytes);
        return Base64.encodeToString(bytes, Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }

    private static boolean uidOwnsPackage(Context context, int uid, String expected) {
        String[] packages = context.getPackageManager().getPackagesForUid(uid);
        if (packages == null) return false;
        for (String name : packages) if (expected.equals(name)) return true;
        return false;
    }

    private static boolean packageInstalled(Context context, String packageName) {
        try {
            context.getPackageManager().getPackageInfo(packageName, 0);
            return true;
        } catch (PackageManager.NameNotFoundException ignored) {
            return false;
        }
    }

    private static boolean packageHasCertificate(Context context, String packageName, String expected) {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(
                packageName, PackageManager.GET_SIGNING_CERTIFICATES
            );
            if (info.signingInfo == null) return false;
            Signature[] signatures = info.signingInfo.getApkContentsSigners();
            if (signatures == null) return false;
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (Signature signature : signatures) {
                byte[] hash = digest.digest(signature.toByteArray());
                StringBuilder hex = new StringBuilder(hash.length * 2);
                for (byte value : hash) hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 0xff));
                if (expected.equals(hex.toString())) return true;
            }
        } catch (Throwable ignored) {
            return false;
        }
        return false;
    }

    private boolean isQqGrant(Uri uri) {
        Context context = getContext();
        if (context == null || uri == null) return false;
        if (!uidOwnsPackage(context, Binder.getCallingUid(), QQ_PACKAGE)) return false;
        if (uri.getPathSegments().size() != 2 || !"apk".equals(uri.getPathSegments().get(0))) return false;
        String token = uri.getPathSegments().get(1);
        Long expires = grants.get(token);
        if (expires == null) return false;
        if (System.currentTimeMillis() > expires) {
            grants.remove(token);
            return false;
        }
        return true;
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        if (!isQqGrant(uri)) throw new SecurityException("APK URI is restricted to QQ");
        String[] columns = projection == null
            ? new String[] { OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE }
            : projection;
        MatrixCursor cursor = new MatrixCursor(columns, 1);
        File apk = installedApk();
        if (apk == null || !apk.isFile()) return cursor;
        Object[] values = new Object[columns.length];
        for (int i = 0; i < columns.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(columns[i])) values[i] = "EffectCraft.apk";
            else if (OpenableColumns.SIZE.equals(columns[i])) values[i] = apk.length();
        }
        cursor.addRow(values);
        return cursor;
    }

    @Override public String getType(Uri uri) {
        if (!isQqGrant(uri)) throw new SecurityException("APK URI is restricted to QQ");
        return "application/vnd.android.package-archive";
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read-only APK sharing is supported");
        if (!isQqGrant(uri)) throw new SecurityException("APK URI is restricted to QQ");
        File apk = installedApk();
        if (apk == null || !apk.isFile()) throw new FileNotFoundException("Installed EffectCraft APK was not found");
        return ParcelFileDescriptor.open(apk, ParcelFileDescriptor.MODE_READ_ONLY);
    }

    private File installedApk() {
        Context context = getContext();
        if (context == null) return null;
        try {
            return new File(context.getApplicationInfo().sourceDir);
        } catch (Throwable ignored) {
            return null;
        }
    }

    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException("Read-only provider"); }
    @Override public int delete(Uri uri, String selection, String[] selectionArgs) { throw new UnsupportedOperationException("Read-only provider"); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) { throw new UnsupportedOperationException("Read-only provider"); }
}
