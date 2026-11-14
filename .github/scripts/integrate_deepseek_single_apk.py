#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import runpy
import sys
from pathlib import Path

def once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {n}")
    return text.replace(old, new, 1)

def replace_java_method(source: str, signature: str, body: str) -> str:
    pattern = re.compile(r"(?m)^    " + re.escape(signature) + r" \{.*?^    \}", re.S)
    updated, count = pattern.subn(body, source, count=1)
    if count != 1:
        raise SystemExit(f"Could not safely replace Java bridge method: {signature}")
    return updated

def main() -> None:
    effectcraft = Path(os.environ["EFFECTCRAFT_DIR"]).resolve()
    builder = Path(os.environ["ARTCRAFT_DIR"]).resolve()
    llama = Path(os.environ["LLAMA_CPP_DIR"]).resolve()
    repo = Path(__file__).resolve().parents[2]
    plugin_src = repo / "android-ai-plugin" / "app" / "src" / "main" / "java" / "com" / "artcraft" / "effectcraft" / "aiassistant"
    catalog_src = repo / "android-ai-plugin" / "gradle" / "libs.versions.toml"
    legacy_bridge = repo / ".github" / "scripts" / "install_ai_plugin_bridge.py"
    for required in (
        effectcraft / "crates/ui-egui",
        builder / "lib/build-common.sh",
        builder / "lib/android_project.py",
        builder / "templates/android/SafActivity.java",
        llama / "examples/llama.android/lib/build.gradle.kts",
        llama / "examples/llama.android/lib/src/main/cpp/CMakeLists.txt",
        llama / "examples/llama.android/lib/src/main/cpp/logging.h",
        llama / "examples/llama.android/lib/src/main/cpp/ai_chat.cpp",
        plugin_src / "InferenceService.kt",
        plugin_src / "PluginManagerActivity.kt",
        catalog_src,
        legacy_bridge,
    ):
        if not required.exists():
            raise SystemExit(f"Required integrated DeepSeek build input is missing: {required}")

    # Copy the Android sources and catalog into the builder checkout because the workflow
    # cleans the source bundle before Gradle generates the project.
    embedded_ai_dir = builder / "effectcraft-ai-source"
    embedded_ai_dir.mkdir(parents=True, exist_ok=True)
    for ai_file in ("InferenceService.kt", "PluginManagerActivity.kt"):
        (embedded_ai_dir / ai_file).write_bytes((plugin_src / ai_file).read_bytes())
    embedded_catalog = builder / "effectcraft-ai-libs.versions.toml"
    embedded_catalog.write_bytes(catalog_src.read_bytes())

    os.environ["EFFECTCRAFT_AI_SOURCE"] = str(embedded_ai_dir)
    os.environ["EFFECTCRAFT_AI_CATALOG"] = str(embedded_catalog)
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as env_file:
            env_file.write(f"EFFECTCRAFT_AI_SOURCE={embedded_ai_dir}\n")
            env_file.write(f"EFFECTCRAFT_AI_CATALOG={embedded_catalog}\n")
            env_file.write(f"LLAMA_CPP_DIR={llama}\n")

    # Reuse the already-tested host UI/JNI wiring, then replace its package installer IPC
    # with an in-process service binding. This preserves the existing assistant state wiring.
    sys.argv = [str(legacy_bridge)]
    runpy.run_path(str(legacy_bridge), run_name="__main__")

    # Stage the Kotlin model manager and inference service beside the generated NativeActivity.
    common = builder / "lib/build-common.sh"
    c = common.read_text(encoding="utf-8")
    import_anchor = "from pathlib import Path\nimport re, shutil, sys, tomllib"
    if "EFFECTCRAFT_DEEPSEEK_SINGLE_APK_V1" not in c:
        c = once(c, import_anchor, "from pathlib import Path\nimport os\nimport re, shutil, sys, tomllib",
                 "build-common Python environment import")
        java_anchor = """        (java_dir / f"{saf['activity']}.java").write_text(java_src)
"""
        java_add = java_anchor + """        # EFFECTCRAFT_DEEPSEEK_SINGLE_APK_V1: both Kotlin components live in the host APK.
        ai_source = Path(os.environ["EFFECTCRAFT_AI_SOURCE"])
        ai_dir = java_dir / "aiassistant"
        ai_dir.mkdir(parents=True, exist_ok=True)
        for ai_file in ("InferenceService.kt", "PluginManagerActivity.kt"):
            source_file = ai_source / ai_file
            if not source_file.is_file():
                raise SystemExit(f"Missing embedded DeepSeek source: {source_file}")
            (ai_dir / ai_file).write_bytes(source_file.read_bytes())
"""
        c = once(c, java_anchor, java_add, "launcher Kotlin source staging")
        common.write_text(c, encoding="utf-8")

    # Make llama.cpp's Android library compatible with the host app's API 28 minimum and
    # the mobile memory target already chosen for this project.
    lib_gradle = llama / "examples/llama.android/lib/build.gradle.kts"
    lg = lib_gradle.read_text(encoding="utf-8")
    if "minSdk = 33" in lg:
        lg = lg.replace("minSdk = 33", "minSdk = 28", 1)
    elif "minSdk = 28" not in lg:
        raise SystemExit("Unexpected llama.cpp Android library minSdk; refusing an unsafe patch.")

    # The host APK generator already places AGP and Kotlin Gradle plugins on the
    # shared build classpath. Resolving version-catalog aliases again in this included
    # library module causes Gradle's "plugin already on the classpath with an unknown
    # version" error. Apply the host-resolved plugin implementations without requesting
    # a second plugin version.
    old_plugin_block = """plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.jetbrains.kotlin.android)
}"""
    new_plugin_block = """plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}"""
    if old_plugin_block in lg:
        lg = once(lg, old_plugin_block, new_plugin_block, "llama.cpp host Gradle plugin classpath alignment")
    elif new_plugin_block not in lg:
        raise SystemExit("Unexpected llama.cpp Android library plugin block; refusing an unsafe Gradle patch.")
    if "minSdk = 28" not in lg:
        raise SystemExit("DeepSeek runtime minSdk did not remain at API 28 after Gradle plugin alignment.")
    lib_gradle.write_text(lg, encoding="utf-8")

    logging = llama / "examples/llama.android/lib/src/main/cpp/logging.h"
    log_text = logging.read_text(encoding="utf-8")
    old_log = """static inline int ai_should_log(int prio) {
    return __android_log_is_loggable(prio, LOG_TAG, LOG_MIN_LEVEL);
}"""
    new_log = """static inline int ai_should_log(int prio) {
#if defined(__ANDROID_API__) && __ANDROID_API__ >= 30
    return __android_log_is_loggable(prio, LOG_TAG, LOG_MIN_LEVEL);
#else
    return prio >= LOG_MIN_LEVEL;
#endif
}"""
    if old_log in log_text:
        logging.write_text(log_text.replace(old_log, new_log, 1), encoding="utf-8")
    elif "defined(__ANDROID_API__) && __ANDROID_API__ >= 30" not in log_text:
        raise SystemExit("Unexpected llama.cpp Android logging helper; refusing an unsafe compatibility patch.")

    ai_cpp = llama / "examples/llama.android/lib/src/main/cpp/ai_chat.cpp"
    ai_text = ai_cpp.read_text(encoding="utf-8")
    for old, new in (
        ("constexpr int   DEFAULT_CONTEXT_SIZE    = 8192;", "constexpr int   DEFAULT_CONTEXT_SIZE    = 1536;"),
        ("constexpr int   BATCH_SIZE              = 512;", "constexpr int   BATCH_SIZE              = 128;"),
    ):
        if old in ai_text:
            ai_text = ai_text.replace(old, new, 1)
        elif new not in ai_text:
            raise SystemExit(f"Could not safely tune llama.cpp mobile setting: {old}")
    ai_cpp.write_text(ai_text, encoding="utf-8")

    # Patch the generated Android Gradle project to compile Kotlin and the llama.cpp
    # Android library as an internal module in the same signed APK.
    generator = builder / "lib/android_project.py"
    g = generator.read_text(encoding="utf-8")
    if "import os\n" not in g:
        g = once(g, "import re\n", "import os\nimport re\n", "Android generator os import")

    app_end = '    lines.append("    </application>")\n'
    app_add = """    # Local DeepSeek manager and inference service are private components inside this APK.
    lines.append('        <activity android:name="com.artcraft.effectcraft.aiassistant.PluginManagerActivity" android:exported="false" android:label="EffectCraft DeepSeek 模型管理" />')
    lines.append('        <service android:name="com.artcraft.effectcraft.aiassistant.InferenceService" android:exported="false" />')
""" + app_end
    if "com.artcraft.effectcraft.aiassistant.PluginManagerActivity" not in g:
        g = once(g, app_end, app_add, "integrated DeepSeek manifest components")

    # Remove no-longer-needed package installer / external package visibility declarations
    # which the legacy bridge added before the single-APK decision.
    for line in (
        "        '    <uses-permission android:name=\"android.permission.REQUEST_INSTALL_PACKAGES\" />',\n",
        "        '    <queries><package android:name=\"com.artcraft.effectcraft.aiassistant\" /></queries>',\n",
        "        '    <permission android:name=\"com.artcraft.effectcraft.permission.BIND_AI_PLUGIN\" android:protectionLevel=\"signature\" />',\n",
    ):
        g = g.replace(line, "")

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

    settings_fn_anchor = 'def settings_gradle(app):\n    return f"""'
    settings_fn_add = 'def settings_gradle(app):\n    ai_runtime_project_dir = _groovy(str(Path(os.environ[\'LLAMA_CPP_DIR\']).resolve() / \'examples/llama.android/lib\'))\n    return f"""'
    if "ai_runtime_project_dir =" not in g:
        g = once(g, settings_fn_anchor, settings_fn_add, "llama.cpp Gradle project path setup")
    settings_anchor = "rootProject.name = '{_groovy(app)}-android'\n"
    settings_add = settings_anchor + """include ':ai-runtime'
project(':ai-runtime').projectDir = file('{ai_runtime_project_dir}')
"""
    if "include ':ai-runtime'" not in g:
        g = once(g, settings_anchor, settings_add, "llama.cpp Android library module inclusion")

    gradle_dir_anchor = '    gradle_dir.mkdir(parents=True, exist_ok=True)\n'
    catalog_copy = gradle_dir_anchor + """    # The embedded llama.cpp module uses the version catalog for its Kotlin/AGP plugins.
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

    # Replace external companion-package calls with explicit, in-process Android service calls.
    java = builder / "templates/android/SafActivity.java"
    j = java.read_text(encoding="utf-8")
    # The host Activity is in com.artcraft.effectcraft; the Kotlin components are
    # staged in the sibling aiassistant package and must be imported for javac.
    ai_imports = (
        "import com.artcraft.effectcraft.aiassistant.InferenceService;\\n"
        "import com.artcraft.effectcraft.aiassistant.PluginManagerActivity;\\n"
    )
    if "import com.artcraft.effectcraft.aiassistant.InferenceService;" not in j or \
            "import com.artcraft.effectcraft.aiassistant.PluginManagerActivity;" not in j:
        j = once(
            j,
            "import android.content.Context;\\n",
            "import android.content.Context;\\n" + ai_imports,
            "integrated DeepSeek Kotlin component imports",
        )
    j = replace_java_method(j, "public static boolean isAiPluginInstalled()",
        """    public static boolean isAiPluginInstalled() {
        return aiActivity.get() != null;
    }""")
    j = replace_java_method(j, "public static void openAiPluginImport()",
        """    public static void openAiPluginImport() {
        openAiPluginManager();
    }""")
    j = replace_java_method(j, "public static void openAiPluginManager()",
        """    public static void openAiPluginManager() {
        __CLASS__ activity = aiActivity.get();
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            try {
                activity.startActivity(new Intent(activity, PluginManagerActivity.class));
            } catch (Exception error) {
                Log.e(TAG, "Could not open the built-in DeepSeek model manager.", error);
            }
        });
    }""")
    j = replace_java_method(j, "private boolean ensureAiBound()",
        """    private boolean ensureAiBound() {
        if (aiService != null || aiBinding) return true;
        Intent intent = new Intent(this, InferenceService.class);
        try {
            aiBinding = bindService(intent, aiConnection, Context.BIND_AUTO_CREATE);
        } catch (Exception error) {
            Log.e(TAG, "Could not bind the in-app DeepSeek service.", error);
            aiBinding = false;
        }
        return aiBinding;
    }""")
    j = replace_java_method(j, "public static boolean submitAiPrompt(String requestId, String prompt)",
        """    public static boolean submitAiPrompt(String requestId, String prompt) {
        __CLASS__ activity = aiActivity.get();
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
    }""")
    java.write_text(j, encoding="utf-8")

    # Remove the "import companion plugin" control from the in-app assistant. Model management
    # remains as an in-app screen; the user never imports a ZIP or installs another APK.
    assistant = repo / ".github/scripts/ai_assistant_plugin.rs"
    a = assistant.read_text(encoding="utf-8")
    text_replacements = (
        ("你好！我是 EffectCraft AI 助手。导入 DeepSeek AI 插件 ZIP 并准备本地模型后，即可在这里离线对话。",
         "你好！我是 EffectCraft 内置 DeepSeek AI 助手。首次使用时，在模型管理中下载本地模型后即可离线对话。"),
        ('ui.label("DeepSeek 本地推理 · 插件通过 ZIP 导入");',
         'ui.label("DeepSeek 本地推理 · 已集成在当前 APK");'),
        ('ui.small("AI 插件已导入；首次使用请先准备模型。");',
         'ui.small("内置 AI 引擎已就绪；首次使用请先下载模型。");'),
        ('ui.colored_label(Color32::from_rgb(210, 145, 35), "尚未导入 DeepSeek AI 插件 ZIP。");',
         'ui.colored_label(Color32::from_rgb(210, 145, 35), "正在初始化内置 DeepSeek AI 引擎…");'),
        ('if ui.button("导入 AI 插件").clicked() {\n                    import_plugin = true;\n                }\n                ', ''),
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
    )
    for old, new in text_replacements:
        if old in a:
            a = a.replace(old, new, 1)
    a = a.replace('    let mut import_plugin = false;\n', '', 1)
    import_block = """    if import_plugin {
        match open_ai_plugin_import() {
            Ok(()) => {
                state.notice = "请选择 DeepSeek AI 插件 ZIP。随后 Android 会显示一次系统安装确认。".into();
            }
            Err(error) => state.notice = error,
        }
    }
"""
    a = a.replace(import_block, "", 1)
    if 'ui.button("导入 AI 插件")' in a or "请先点击“导入 AI 插件”" in a:
        raise SystemExit("AI assistant still contains a companion-plugin import path; refusing to claim single-APK integration.")
    assistant.write_text(a, encoding="utf-8")

    print("DeepSeek model manager and inference service are staged inside the main APK.")
    print("The host binds to its own in-process Android service; no companion APK/ZIP is needed.")
    print("The approximately 1.02 GB GGUF model remains a one-time download inside the APK's app-private storage.")
    print("Inference remains local/offline after the model download.")

if __name__ == "__main__":
    main()
