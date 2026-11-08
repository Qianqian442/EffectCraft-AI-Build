# EffectCraft AI 助手插件（原型）

独立 Android 伴随应用，包名 com.artcraft.effectcraft.aiassistant，支持 arm64-v8a，最低 Android 9 / API 28。

本地推理使用 llama-cpp 0.1.161。DeepSeek-R1-Distill-Qwen-1.5B IQ4_XS GGUF 模型保存在插件私有目录，不打包进插件 APK。首次使用可下载模型，也可通过 Android 文件选择器导入现有 GGUF 文件。

本阶段只构建并验证独立插件 APK 的安装与启动。EffectCraft 主程序的启动入口和 JNI 桥接属于后续集成步骤。在独立应用及主程序调用验证通过前，不从主 APK 移除现有 AI 实现。

注意：EffectCraft 当前“导入插件”按钮只接收 WASM/WAT 文件；安装本 APK 必须使用 Android 系统 APK 安装器。
