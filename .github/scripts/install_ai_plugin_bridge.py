#!/usr/bin/env python3
from __future__ import annotations
import os
from pathlib import Path

PLUGIN = "com.artcraft.effectcraft.aiassistant"
PERMISSION = "com.artcraft.effectcraft.permission.BIND_AI_PLUGIN"

def once(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    n = text.count(old)
    if n != count:
        raise SystemExit(f"{label}: expected {count} occurrence(s), got {n}")
    return text.replace(old, new, count)

def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    builder = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    helper = Path(__file__).with_name("ai_assistant_plugin.rs")
    if not effectcraft.is_dir() or not builder.is_dir() or not helper.is_file():
        raise SystemExit("EffectCraft, Android builder, or AI bridge source is missing.")

    ui = effectcraft / "crates/ui-egui"
    (ui / "src/ai_assistant.rs").write_text(helper.read_text(encoding="utf-8"), encoding="utf-8")

    cargo = ui / "Cargo.toml"
    c = cargo.read_text(encoding="utf-8")
    c = "\n".join(x for x in c.splitlines() if "llama-cpp-2 =" not in x and "llama-cpp-sys-2 =" not in x) + "\n"
    if 'jni = "0.22"' not in c:
        c = once(c, "[dev-dependencies]\n",
                 '[target.\'cfg(target_os = "android")\'.dependencies]\njni = "0.22"\n\n[dev-dependencies]\n',
                 "JNI dependency")
    cargo.write_text(c, encoding="utf-8")

    lib = ui / "src/lib.rs"
    c = lib.read_text(encoding="utf-8")
    if "init_android_ai_bridge" not in c:
        c = once(c, "mod ai_assistant;\n",
                 "mod ai_assistant;\n\n#[cfg(target_os = \"android\")]\npub fn init_android_ai_bridge(vm_ptr: *mut std::ffi::c_void) {\n    ai_assistant::init_android_vm(vm_ptr);\n}\n",
                 "AI bridge export")
        lib.write_text(c, encoding="utf-8")

    build_common = builder / "lib/build-common.sh"
    c = build_common.read_text(encoding="utf-8")
    anchor = "egui_winit::android_activity::set_vm(android_app.vm_as_ptr());"
    if "init_android_ai_bridge" not in c:
        c = once(c, anchor, anchor + "\n    effectcraft_ui_egui::init_android_ai_bridge(android_app.vm_as_ptr());",
                 "Android launcher VM setup", 2)
        build_common.write_text(c, encoding="utf-8")

    # Android 11+ package visibility, Android package-installer permission,
    # and a signature-level permission guarding the companion service.
    generator = builder / "lib/android_project.py"
    c = generator.read_text(encoding="utf-8")
    anchor = """        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">',
"""
    additions = """        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">',
        '    <uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />',
        '    <queries><package android:name="com.artcraft.effectcraft.aiassistant" /></queries>',
        '    <permission android:name="com.artcraft.effectcraft.permission.BIND_AI_PLUGIN" android:protectionLevel="signature" />',
"""
    if PERMISSION not in c:
        c = once(c, anchor, additions, "Android manifest additions")
        generator.write_text(c, encoding="utf-8")

    java = builder / "templates/android/SafActivity.java"
    c = java.read_text(encoding="utf-8")
    extra_imports = [
        "import android.app.PendingIntent;",
        "import android.content.BroadcastReceiver;",
        "import android.content.ComponentName;",
        "import android.content.IntentFilter;",
        "import android.content.ServiceConnection;",
        "import android.content.pm.PackageInstaller;",
        "import android.os.IBinder;",
        "import android.os.Message;",
        "import android.os.Messenger;",
        "import android.os.RemoteException;",
        "import java.lang.ref.WeakReference;",
        "import java.util.concurrent.ConcurrentHashMap;",
    ]
    if "import android.app.PendingIntent;" not in c:
        c = once(c, "import android.content.Context;\n",
                 "import android.content.Context;\n" + "\n".join(extra_imports) + "\n",
                 "AI bridge Java imports")

    class_anchor = "public final class __CLASS__ extends NativeActivity {\n"
    fields = r'''
    // EFFECTCRAFT_ANDROID_AI_PLUGIN_BRIDGE_V1
    private static final String AI_PACKAGE = "com.artcraft.effectcraft.aiassistant";
    private static final String AI_BIND_ACTION = "com.artcraft.effectcraft.aiassistant.BIND_INFERENCE";
    private static final String AI_INSTALL_ACTION = "__PACKAGE__.AI_PLUGIN_INSTALL_RESULT";
    private static final int REQ_AI_PICKER = 0x5047;
    private static final int REQ_AI_PERMISSION = 0x5048;
    private static final int AI_GENERATE = 1;
    private static final int AI_RESPONSE = 2;
    private static volatile WeakReference<__CLASS__> aiActivity = new WeakReference<>(null);
    private final ConcurrentLinkedQueue<Bundle> aiPending = new ConcurrentLinkedQueue<>();
    private final ConcurrentHashMap<String, String> aiResponses = new ConcurrentHashMap<>();
    private Messenger aiService;
    private boolean aiBinding;
    private boolean aiReceiverRegistered;
    private Uri aiPendingUri;

    private final Handler aiReplyHandler = new Handler(Looper.getMainLooper()) {
        @Override public void handleMessage(Message message) {
            if (message.what == AI_RESPONSE && message.getData() != null) {
                Bundle data = message.getData();
                String id = data.getString("requestId", "");
                if (!id.isEmpty()) aiResponses.put(id, data.getString("response", "ERROR: AI 插件无返回内容。"));
            }
        }
    };
    private final Messenger aiReplyMessenger = new Messenger(aiReplyHandler);

    private final ServiceConnection aiConnection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            aiService = new Messenger(binder);
            aiBinding = true;
            flushAiRequests();
        }
        @Override public void onServiceDisconnected(ComponentName name) {
            aiService = null;
            aiBinding = false;
        }
        @Override public void onBindingDied(ComponentName name) {
            aiService = null;
            aiBinding = false;
        }
        @Override public void onNullBinding(ComponentName name) {
            aiService = null;
            aiBinding = false;
        }
    };

    private final BroadcastReceiver aiInstallReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
            if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                Intent confirmation = intent.getParcelableExtra(Intent.EXTRA_INTENT);
                if (confirmation != null) startActivity(confirmation);
            } else if (status == PackageInstaller.STATUS_SUCCESS) {
                Log.i(TAG, "EffectCraft AI plugin installed.");
                ensureAiBound();
            } else {
                Log.w(TAG, "AI plugin installation failed: " +
                    intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE));
            }
        }
    };

    public static boolean isAiPluginInstalled() {
        __CLASS__ activity = aiActivity.get();
        if (activity == null) return false;
        try {
            activity.getPackageManager().getPackageInfo(AI_PACKAGE, 0);
            return true;
        } catch (PackageManager.NameNotFoundException ignored) {
            return false;
        }
    }

    public static boolean submitAiPrompt(String requestId, String prompt) {
        __CLASS__ activity = aiActivity.get();
        if (activity == null || requestId == null || prompt == null || !isAiPluginInstalled()) return false;
        Bundle data = new Bundle();
        data.putString("requestId", requestId);
        data.putString("prompt", prompt);
        activity.aiPending.add(data);
        if (!activity.ensureAiBound()) {
            activity.aiPending.remove(data);
            activity.aiResponses.put(requestId, "ERROR: 无法连接 AI 插件服务，请重新安装插件。");
            return true;
        }
        activity.flushAiRequests();
        return true;
    }

    public static String pollAiResponse(String requestId) {
        __CLASS__ activity = aiActivity.get();
        return activity == null ? null : activity.aiResponses.remove(requestId);
    }

    public static void openAiPluginImport() {
        __CLASS__ activity = aiActivity.get();
        if (activity != null) activity.runOnUiThread(activity::chooseAiPlugin);
    }

    public static void openAiPluginManager() {
        __CLASS__ activity = aiActivity.get();
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            Intent launch = activity.getPackageManager().getLaunchIntentForPackage(AI_PACKAGE);
            if (launch != null) activity.startActivity(launch);
            else Log.w(TAG, "AI plugin model manager activity was not found.");
        });
    }

    private boolean ensureAiBound() {
        if (aiService != null || aiBinding) return true;
        if (!isAiPluginInstalled()) return false;
        Intent intent = new Intent(AI_BIND_ACTION);
        intent.setComponent(new ComponentName(AI_PACKAGE, AI_PACKAGE + ".InferenceService"));
        try {
            aiBinding = bindService(intent, aiConnection, Context.BIND_AUTO_CREATE);
        } catch (SecurityException | IllegalArgumentException error) {
            Log.e(TAG, "Could not bind the AI plugin service.", error);
            aiBinding = false;
        }
        return aiBinding;
    }

    private void flushAiRequests() {
        if (aiService == null) return;
        Bundle data;
        while ((data = aiPending.poll()) != null) {
            Message message = Message.obtain(null, AI_GENERATE);
            message.setData(data);
            message.replyTo = aiReplyMessenger;
            try {
                aiService.send(message);
            } catch (RemoteException error) {
                String id = data.getString("requestId", "");
                if (!id.isEmpty()) aiResponses.put(id, "ERROR: AI 插件连接中断，请重试。");
                aiService = null;
                aiBinding = false;
                break;
            }
        }
    }

    private void chooseAiPlugin() {
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        picker.addCategory(Intent.CATEGORY_OPENABLE);
        picker.setType("application/vnd.android.package-archive");
        picker.putExtra(Intent.EXTRA_TITLE, "选择 EffectCraft AI 插件 APK");
        picker.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(picker, REQ_AI_PICKER);
    }

    private void installAiPlugin(Uri uri) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !getPackageManager().canRequestPackageInstalls()) {
            aiPendingUri = uri;
            Intent settings = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES);
            settings.setData(Uri.parse("package:" + getPackageName()));
            startActivityForResult(settings, REQ_AI_PERMISSION);
            return;
        }
        io.execute(() -> createAiInstallSession(uri));
    }

    private void createAiInstallSession(Uri uri) {
        File archive = new File(getCacheDir(), "effectcraft-ai-plugin.apk");
        try (InputStream input = getContentResolver().openInputStream(uri);
             FileOutputStream output = new FileOutputStream(archive, false)) {
            if (input == null) throw new IllegalStateException("无法读取 AI 插件 APK。");
            byte[] buffer = new byte[1024 * 1024];
            int n;
            while ((n = input.read(buffer)) != -1) output.write(buffer, 0, n);
            output.flush();
            output.getFD().sync();
        } catch (Exception error) {
            archive.delete();
            Log.e(TAG, "Could not copy AI plugin APK.", error);
            return;
        }

        try {
            android.content.pm.PackageInfo info = getPackageManager().getPackageArchiveInfo(archive.getAbsolutePath(), 0);
            if (info == null || !AI_PACKAGE.equals(info.packageName)) {
                throw new IllegalStateException("所选文件不是 EffectCraft AI 插件 APK。");
            }
            PackageInstaller installer = getPackageManager().getPackageInstaller();
            PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            params.setAppPackageName(AI_PACKAGE);
            int id = installer.createSession(params);
            try (PackageInstaller.Session session = installer.openSession(id);
                 FileInputStream input = new FileInputStream(archive);
                 OutputStream output = session.openWrite("ai-plugin.apk", 0, archive.length())) {
                byte[] buffer = new byte[1024 * 1024];
                int n;
                while ((n = input.read(buffer)) != -1) output.write(buffer, 0, n);
                session.fsync(output);
                Intent status = new Intent(AI_INSTALL_ACTION).setPackage(getPackageName());
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) flags |= PendingIntent.FLAG_MUTABLE;
                PendingIntent result = PendingIntent.getBroadcast(this, id, status, flags);
                session.commit(result.getIntentSender());
            }
        } catch (Exception error) {
            Log.e(TAG, "Could not install AI plugin APK.", error);
        } finally {
            archive.delete();
        }
    }

    private void initAiBridge() {
        aiActivity = new WeakReference<>(this);
        try {
            registerReceiver(aiInstallReceiver, new IntentFilter(AI_INSTALL_ACTION));
            aiReceiverRegistered = true;
        } catch (Exception error) {
            Log.w(TAG, "Could not register the AI plugin installer callback.", error);
        }
        ensureAiBound();
    }

    private void cleanupAiBridge() {
        aiActivity = new WeakReference<>(null);
        if (aiBinding) {
            try { unbindService(aiConnection); } catch (Exception ignored) {}
            aiBinding = false;
            aiService = null;
        }
        if (aiReceiverRegistered) {
            try { unregisterReceiver(aiInstallReceiver); } catch (Exception ignored) {}
            aiReceiverRegistered = false;
        }
    }

'''
    if "EFFECTCRAFT_ANDROID_AI_PLUGIN_BRIDGE_V1" not in c:
        c = once(c, class_anchor, class_anchor + fields, "AI plugin bridge Java API")

    create_anchor = "        super.onCreate(savedInstanceState);\n"
    if "initAiBridge();" not in c:
        c = once(c, create_anchor, create_anchor + "        initAiBridge();\n", "AI bridge lifecycle setup")

    resume_anchor = """    @Override
    protected void onNewIntent(Intent intent) {
"""
    resume = """    @Override
    protected void onResume() {
        super.onResume();
        ensureAiBound();
    }

"""
    if "protected void onResume()" not in c:
        c = once(c, resume_anchor, resume + resume_anchor, "AI service reconnect hook")

    result_anchor = "        super.onActivityResult(requestCode, resultCode, data);\n"
    result = """        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_AI_PICKER) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) installAiPlugin(data.getData());
            return;
        }
        if (requestCode == REQ_AI_PERMISSION) {
            Uri pending = aiPendingUri;
            aiPendingUri = null;
            if (pending != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                    && getPackageManager().canRequestPackageInstalls()) installAiPlugin(pending);
            else if (pending != null) Log.w(TAG, "Unknown-source installation permission was not granted.");
            return;
        }
"""
    if "requestCode == REQ_AI_PICKER" not in c:
        c = once(c, result_anchor, result, "AI plugin installer activity result")

    destroy_anchor = "    protected void onDestroy() {\n"
    if "cleanupAiBridge();" not in c:
        c = once(c, destroy_anchor, destroy_anchor + "        cleanupAiBridge();\n", "AI bridge activity teardown")

    java.write_text(c, encoding="utf-8")

    print("EffectCraft host UI now uses the independent AI plugin service.")
    print("The host removes llama.cpp and the bundled model; the plugin owns local inference.")
    print("AI plugin import uses Android PackageInstaller and Messenger IPC with signature permission.")


if __name__ == "__main__":
    main()
