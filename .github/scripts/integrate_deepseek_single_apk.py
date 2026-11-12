#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

def once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {n}")
    return text.replace(old, new, 1)

def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    builder = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    llama = Path(os.environ["LLAMA_CPP_DIR"]).resolve()
    repo = Path(__file__).resolve().parents[2]
    plugin_src = repo / "android-ai-plugin" / "app" / "src" / "main" / "java" / "com" / "artcraft" / "effectcraft" / "aiassistant"
    catalog_src = repo / "android-ai-plugin" / "gradle" / "libs.versions.toml"
    for required in (effectcraft / "crates/ui-egui", builder / "lib/build-common.sh",
                     builder / "lib/android_project.py", builder / "templates/android/SafActivity.java",
                     llama / "examples/llama.android/lib/build.gradle.kts",
                     plugin_src / "InferenceService.kt", plugin_src / "PluginManagerActivity.kt",
                     catalog_src):
        if not required.exists():
            raise SystemExit(f"Required integrated DeepSeek build input is missing: {required}")

    # 1) Copy the plugin's model manager and inference service into the host APK's Java/Kotlin tree.
    common = builder / "lib/build-common.sh"
    c = common.read_text(encoding="utf-8")
    import_anchor = "from pathlib import Path\nimport re, shutil, sys, tomllib"
    c = once(c, import_anchor, "from pathlib import Path\nimport os\nimport re, shutil, sys, tomllib",
             "build-common Python environment import")
    java_anchor = """        (java_dir / f"{saf['activity']}.java").write_text(java_src)
"""
    java_add = java_anchor + """        # EFFECTCRAFT_DEEPSEEK_SINGLE_APK_V1: package the local inference service and model manager
        # as Kotlin classes in the same application package; no companion APK is installed.
        ai_source = Path(os.environ["EFFECTCRAFT_AI_SOURCE"])
        ai_dir = java_dir / "aiassistant"
        ai_dir.mkdir(parents=True, exist_ok=True)
        for ai_file in ("InferenceService.kt", "PluginManagerActivity.kt"):
            source_file = ai_source / ai_file
            if not source_file.is_file():
                raise SystemExit(f"Missing embedded DeepSeek source: {source_file}")
            (ai_dir / ai_file).write_bytes(source_file.read_bytes())
"""
    if "EFFECTCRAFT_DEEPSEEK_SINGLE_APK_V1" not in c:
        c = once(c, java_anchor, java_add, "launcher Kotlin source staging")
    common.write_text(c, encoding="utf-8")

    # 2) Patch the Android project generator: Kotlin plugin, llama.cpp library module,
    # version catalog, dependencies, and in-app Activity/Service manifest declarations.
    generator = builder / "lib/android_project.py"
    g = generator.read_text(encoding="utf-8")
    if "import os\n" not in g:
        g = once(g, "import re\n", "import os\nimport re\n", "Android generator os import")

    manifest_anchor = '    application = android_meta.get("application") or {}\n'
    manifest_add = """    existing_permissions = {item.get("name") for item in _as_list(android_meta.get("uses_permission"))}
    for required_permission in ("android.permission.INTERNET", "android.permission.ACCESS_NETWORK_STATE"):
        if required_permission not in existing_permissions:
            lines.append(f'    <uses-permission android:name="{required_permission}" />')

""" + manifest_anchor
    if "com.artcraft.effectcraft.aiassistant.InferenceService" not in g:
        g = once(g, manifest_anchor, manifest_add, "manifest network permission insertion")

    app_end = '    lines.append("    </application>")\n'
    app_add = """    # DeepSeek is part of this APK. These internal components share the host app's
    # private files directory, so the model manager and inference service use the same GGUF.
    lines.append('        <activity android:name="com.artcraft.effectcraft.aiassistant.PluginManagerActivity" android:exported="false" android:label="EffectCraft DeepSeek 模型管理" />')
    lines.append('        <service android:name="com.artcraft.effectcraft.aiassistant.InferenceService" android:exported="false" />')
""" + app_end
    if "PluginManagerActivity" not in g:
        g = once(g, app_end, app_add, "integrated DeepSeek manifest components")

    plugins_old = """plugins {{
    id 'com.android.application' version '{GRADLE_PLUGIN_VERSION}'
}}"""
    plugins_new = """plugins {{
    id 'com.android.application' version '{GRADLE_PLUGIN_VERSION}'
    id 'org.jetbrains.kotlin.android' version '2.0.21'
}}"""
    if "org.jetbrains.kotlin.android' version '2.0.21'" not in g:
        g = once(g, plugins_old, plugins_new, "Kotlin Android application plugin")

    dep_anchor = "    implementation 'androidx.games:games-activity:4.4.0'\n"
    dep_add = dep_anchor + """    implementation project(':ai-runtime')
    implementation 'androidx.datastore:datastore-preferences:1.2.0'
    implementation 'org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2'
"""
    if "implementation project(':ai-runtime')" not in g:
        g = once(g, dep_anchor, dep_add, "DeepSeek inference runtime dependencies")

    bom_old = "implementation platform('org.jetbrains.kotlin:kotlin-bom:1.8.22')"
    bom_new = "implementation platform('org.jetbrains.kotlin:kotlin-bom:2.0.21')"
    if bom_old in g:
        g = once(g, bom_old, bom_new, "Kotlin BOM alignment")

    settings_anchor = "rootProject.name = '{_groovy(app)}-android'\n"
    settings_add = settings_anchor + """include ':ai-runtime'
project(':ai-runtime').projectDir = file('{_groovy(str(Path(os.environ["LLAMA_CPP_DIR"]).resolve() / "examples/llama.android/lib"))}')
"""
    if "include ':ai-runtime'" not in g:
        g = once(g, settings_anchor, settings_add, "llama.cpp Android library module inclusion")

    gradle_dir_anchor = '    gradle_dir.mkdir(parents=True, exist_ok=True)\n'
    catalog_copy = gradle_dir_anchor + """    # The llama.cpp library uses Gradle's version catalog for its Android/Kotlin plugins.
    catalog_source = Path(os.environ["EFFECTCRAFT_AI_CATALOG"])
    catalog_target = gradle_dir / "gradle" / "libs.versions.toml"
    catalog_target.parent.mkdir(parents=True, exist_ok=True)
    catalog_text = catalog_source.read_text(encoding="utf-8")
    catalog_text = catalog_text.replace('agp = "8.13.2"', 'agp = "8.7.3"')
    catalog_text = catalog_text.replace('kotlin = "2.3.0"', 'kotlin = "2.0.21"')
    if 'agp = "8.7.3"' not in catalog_text or 'kotlin = "2.0.21"' not in catalog_text:
        raise SystemExit("Could not align the embedded llama.cpp version catalog with the host Android Gradle Plugin.")
    catalog_target.write_text(catalog_text, encoding="utf-8")
"""
    if "EFFECTCRAFT_AI_CATALOG" not in g:
        g = once(g, gradle_dir_anchor, catalog_copy, "embedded runtime version catalog")
    generator.write_text(g, encoding="utf-8")

    # 3) Add the internal service bridge to the existing NativeActivity template.
    java = builder / "templates/android/SafActivity.java"
    j = java.read_text(encoding="utf-8")
    class_anchor = "public final class __CLASS__ extends NativeActivity {\n"
    imports = [
        "import android.content.ComponentName;",
        "import android.content.ServiceConnection;",
        "import android.os.IBinder;",
        "import android.os.Message;",
        "import android.os.Messenger;",
        "import android.os.RemoteException;",
        "import android.os.Handler;",
        "import android.os.Looper;",
        "import java.lang.ref.WeakReference;",
        "import java.util.concurrent.ConcurrentHashMap;",
        "import java.util.concurrent.ConcurrentLinkedQueue;",
        "import com.artcraft.effectcraft.aiassistant.InferenceService;",
        "import com.artcraft.effectcraft.aiassistant.PluginManagerActivity;",
    ]
    insertion = ""
    for line in imports:
        if line not in j:
            insertion += line + "\n"
    if insertion:
        j = once(j, "import android.app.NativeActivity;\n",
                 "import android.app.NativeActivity;\n" + insertion,
                 "internal AI service imports")

    fields = r'''
    // EFFECTCRAFT_DEEPSEEK_SINGLE_APK_V1
    private static volatile WeakReference<__CLASS__> aiHost = new WeakReference<>(null);
    private static final int AI_GENERATE = 1;
    private static final int AI_RESPONSE = 2;
    private final ConcurrentLinkedQueue<Bundle> aiPending = new ConcurrentLinkedQueue<>();
    private final ConcurrentHashMap<String, String> aiResponses = new ConcurrentHashMap<>();
    private Messenger aiService;
    private boolean aiBinding;

    private final Handler aiReplyHandler = new Handler(Looper.getMainLooper()) {
        @Override public void handleMessage(Message message) {
            if (message.what == AI_RESPONSE && message.getData() != null) {
                Bundle data = message.getData();
                String id = data.getString("requestId", "");
                if (!id.isEmpty()) aiResponses.put(id, data.getString("response", "ERROR: 本地 AI 没有返回内容。"));
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
            aiService = null; aiBinding = false;
        }
        @Override public void onBindingDied(ComponentName name) {
            aiService = null; aiBinding = false;
        }
        @Override public void onNullBinding(ComponentName name) {
            aiService = null; aiBinding = false;
        }
    };

    public static boolean isAiPluginInstalled() {
        return aiHost.get() != null;
    }

    public static boolean submitAiPrompt(String requestId, String prompt) {
        __CLASS__ activity = aiHost.get();
        if (activity == null || requestId == null || requestId.isEmpty() || prompt == null || prompt.trim().isEmpty()) return false;
        Bundle data = new Bundle();
        data.putString("requestId", requestId);
        data.putString("prompt", prompt);
        activity.aiPending.add(data);
        if (!activity.ensureAiBound()) {
            activity.aiPending.remove(data);
            activity.aiResponses.put(requestId, "ERROR: 无法启动 APK 内置的 DeepSeek 推理服务。");
        } else {
            activity.flushAiRequests();
        }
        return true;
    }

    public static String pollAiResponse(String requestId) {
        __CLASS__ activity = aiHost.get();
        return activity == null ? null : activity.aiResponses.remove(requestId);
    }

    public static void openAiPluginImport() { openAiPluginManager(); }

    public static void openAiPluginManager() {
        __CLASS__ activity = aiHost.get();
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            try {
                activity.startActivity(new Intent(activity, PluginManagerActivity.class));
            } catch (Exception error) {
                Log.e(TAG, "Could not open the built-in DeepSeek model manager.", error);
            }
        });
    }

    private boolean ensureAiBound() {
        if (aiService != null || aiBinding) return true;
        Intent intent = new Intent(this, InferenceService.class);
        try {
            aiBinding = bindService(intent, aiConnection, Context.BIND_AUTO_CREATE);
        } catch (Exception error) {
            Log.e(TAG, "Could not bind the in-app DeepSeek service.", error);
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
                if (!id.isEmpty()) aiResponses.put(id, "ERROR: 本地 DeepSeek 服务连接中断，请重试。");
                aiService = null;
                aiBinding = false;
                break;
            }
        }
    }

    private void initEmbeddedAi() {
        aiHost = new WeakReference<>(this);
        ensureAiBound();
    }

    private void cleanupEmbeddedAi() {
        if (aiHost.get() == this) aiHost = new WeakReference<>(null);
        if (aiBinding) {
            try { unbindService(aiConnection); } catch (Exception ignored) {}
            aiBinding = false;
            aiService = null;
        }
        aiPending.clear();
    }

'''
    if "EFFECTCRAFT_DEEPSEEK_SINGLE_APK_V1" not in j:
        j = once(j, class_anchor, class_anchor + fields, "internal AI host/service API")

    on_create = "        super.onCreate(savedInstanceState);\n"
    if "initEmbeddedAi();" not in j:
        j = once(j, on_create, on_create + "        initEmbeddedAi();\n", "embedded AI initialization")

    resume_anchor = """    @Override
    protected void onNewIntent(Intent intent) {
"""
    resume_hook = """    @Override
    protected void onResume() {
        super.onResume();
        ensureAiBound();
    }

"""
    if "protected void onResume()" not in j:
        j = once(j, resume_anchor, resume_hook + resume_anchor, "embedded AI service reconnect lifecycle")

    destroy_anchor = "    protected void onDestroy() {\n"
    if "cleanupEmbeddedAi();" not in j:
        j = once(j, destroy_anchor, destroy_anchor + "        cleanupEmbeddedAi();\n", "embedded AI lifecycle cleanup")
    java.write_text(j, encoding="utf-8")

    # 4) Use the existing assistant UI but describe the now-internal model manager, not ZIP import.
    assistant = repo / ".github/scripts/ai_assistant_plugin.rs"
    a = assistant.read_text(encoding="utf-8")
    replacements = [
        ("你好！我是 EffectCraft AI 助手。导入 DeepSeek AI 插件 ZIP 并准备本地模型后，即可在这里离线对话。",
         "你好！我是 EffectCraft 内置 DeepSeek AI 助手。首次使用时，请在模型管理中下载本地模型，完成后即可离线对话。"),
        ('ui.label("DeepSeek 本地推理 · 插件通过 ZIP 导入");',
         'ui.label("DeepSeek 本地推理 · 已集成在当前 APK");'),
        ('ui.small("AI 插件已导入；首次使用请先准备模型。");',
         'ui.small("内置 AI 引擎已就绪；首次使用请先下载模型。");'),
        ('ui.colored_label(Color32::from_rgb(210, 145, 35), "尚未导入 DeepSeek AI 插件 ZIP。");',
         'ui.colored_label(Color32::from_rgb(210, 145, 35), "正在初始化内置 DeepSeek AI 引擎…");'),
        ('if ui.button("导入 AI 插件").clicked() {\n                    import_plugin = true;\n                }\n                ',
         ''),
        ('state.notice = "请选择 DeepSeek AI 插件 ZIP。随后 Android 会显示一次系统安装确认。".into();',
         'state.notice = "已打开 APK 内置的 DeepSeek 模型管理。".into();'),
        ('state.notice = "已请求打开 AI 插件的模型管理界面。".into()',
         'state.notice = "已打开本地 DeepSeek 模型管理。".into()'),
        ('state.notice = "请先点击“导入 AI 插件”，选择 ZIP 并按 Android 系统提示完成安装后，即可使用本地 DeepSeek。".into();',
         'state.notice = "请先打开“模型管理”下载约 1.02 GB 的本地 DeepSeek 模型。".into();'),
        ('"无法连接 AI 插件服务，请确认插件已安装后重新打开助手。".into()',
         '"无法连接 APK 内置的 DeepSeek 服务，请重新打开模型管理后重试。".into()'),
        ('Err("独立 AI 插件连接仅在 Android 版本中启用。".into())',
         'Err("APK 内置 DeepSeek 服务仅在 Android 版本中启用。".into())'),
        ('Err("请在 Android 版 EffectCraft 中导入 AI 插件。".into())',
         'Err("请在 Android 版 EffectCraft 中打开本地模型管理。".into())'),
        ('Err("AI 插件模型管理仅在 Android 版本中启用。".into())',
         'Err("DeepSeek 本地模型管理仅在 Android 版本中启用。".into())'),
    ]
    for old, new in replacements:
        if old in a:
            a = a.replace(old, new, 1)
    a = a.replace('    let mut import_plugin = false;\n', '', 1)
    import_block = """    if import_plugin {
        match open_ai_plugin_import() {
            Ok(()) => {
                state.notice = "已打开 APK 内置的 DeepSeek 模型管理。".into();
            }
            Err(error) => state.notice = error,
        }
    }
"""
    if import_block in a:
        a = a.replace(import_block, "", 1)
    assistant.write_text(a, encoding="utf-8")

    print("DeepSeek companion UI, model manager, and inference service are now staged inside the main APK.")
    print("The standalone ZIP-import/install bridge is no longer used by the main APK.")
    print("The approximately 1.02 GB GGUF model remains a one-time in-app download; inference remains local/offline.")

if __name__ == "__main__":
    main()
