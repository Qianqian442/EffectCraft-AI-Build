package com.qianqian.effectcraftadmin;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.database.Cursor;
import android.net.Uri;
import android.os.Binder;
import android.os.Build;
import android.os.Bundle;

import java.security.MessageDigest;

/** Read-only authorization assertion for the official EffectCraft main APK. */
public final class ApkShareAuthorizationProvider extends ContentProvider {
    private static final String MAIN_PACKAGE = "com.artcraft.effectcraft";
    private static final String MAIN_CERT_SHA256 =
        "3709d0d071dbcb63bbc34c70887910f699e07aaaa53bc9c539558d303916068a";

    @Override public boolean onCreate() { return true; }

    @Override
    public Bundle call(String method, String arg, Bundle extras) {
        if (!"is_apk_share_authorized".equals(method)) return super.call(method, arg, extras);
        Context context = getContext();
        if (context == null || !uidOwnsMainPackage(context, Binder.getCallingUid())
                || !mainPackageHasPinnedCertificate(context)) {
            throw new SecurityException("Only the official EffectCraft main APK can query this authorization");
        }

        boolean sessionVerified = context.getSharedPreferences(
            "effectcraft_admin_session", Context.MODE_PRIVATE
        ).getBoolean("verified", false);

        Bundle result = new Bundle();
        result.putBoolean("authorized", sessionVerified);
        result.putString("reason", sessionVerified ? "admin_session_verified" : "admin_login_required");
        return result;
    }

    private static boolean uidOwnsMainPackage(Context context, int uid) {
        String[] packages = context.getPackageManager().getPackagesForUid(uid);
        if (packages == null) return false;
        for (String name : packages) if (MAIN_PACKAGE.equals(name)) return true;
        return false;
    }

    private static boolean mainPackageHasPinnedCertificate(Context context) {
        try {
            PackageManager pm = context.getPackageManager();
            PackageInfo info;
            Signature[] signatures;
            if (Build.VERSION.SDK_INT >= 28) {
                info = pm.getPackageInfo(MAIN_PACKAGE, PackageManager.GET_SIGNING_CERTIFICATES);
                signatures = info.signingInfo == null ? null : info.signingInfo.getApkContentsSigners();
            } else {
                info = pm.getPackageInfo(MAIN_PACKAGE, PackageManager.GET_SIGNATURES);
                signatures = info.signatures;
            }
            if (signatures == null) return false;
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (Signature signature : signatures) {
                byte[] hash = digest.digest(signature.toByteArray());
                StringBuilder hex = new StringBuilder(hash.length * 2);
                for (byte value : hash) hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 0xff));
                if (MAIN_CERT_SHA256.equals(hex.toString())) return true;
            }
        } catch (Throwable ignored) {
            return false;
        }
        return false;
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder) {
        throw new UnsupportedOperationException("Use the read-only authorization call");
    }
    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException("Read-only provider"); }
    @Override public int delete(Uri uri, String selection, String[] selectionArgs) { throw new UnsupportedOperationException("Read-only provider"); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) { throw new UnsupportedOperationException("Read-only provider"); }
}
