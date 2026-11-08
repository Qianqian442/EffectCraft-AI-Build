# EffectCraft DeepSeek AI 插件

独立 Android 插件包名为 `com.artcraft.effectcraft.aiassistant`，仅提供 EffectCraft 的 DeepSeek 本地助手能力，支持 arm64-v8a，最低 Android 9 / API 28。

本地推理使用 llama.cpp。DeepSeek-R1-Distill-Qwen-1.5B IQ4_XS GGUF 模型保存在插件私有目录，不打包进插件 APK；首次使用可在插件中下载模型，也可通过 Android 文件选择器导入 GGUF。模型准备完成后支持离线对话。

EffectCraft 主 APK 通过受签名权限保护的 Android Messenger 服务调用本插件，助手继续显示在 EffectCraft 原来的悬浮助手界面中。插件自身的模型管理页面用于下载、导入和管理模型。

本插件不包含 RIFE 插帧或 Real-ESRGAN 超分；这两项视频 AI 能力继续保留在 EffectCraft 主 APK 中。主 APK 不打包 DeepSeek GGUF 或 llama.cpp 推理依赖。
