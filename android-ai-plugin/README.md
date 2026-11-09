# EffectCraft DeepSeek AI Plugin

This companion runs local DeepSeek inference for the EffectCraft Android host.

## Import package

The downloadable release is `EffectCraft-DeepSeek-AI-Plugin.zip`. It contains:
- `plugin.apk`: the signed ARM64 Android companion package
- `plugin.json`: package metadata and the embedded APK SHA-256

Import the ZIP from EffectCraft's plug-in import entry. The host checks the package name and signing certificate, extracts the companion APK, and invokes Android's PackageInstaller. Android may request the one-time "install unknown apps" permission and a final installation confirmation. This system confirmation is required by Android; the ZIP avoids making users handle a separate APK file manually, but the companion remains an Android-installed package.

- Android package: `com.artcraft.effectcraft.aiassistant`
- Service action: `com.artcraft.effectcraft.aiassistant.BIND_INFERENCE`
- Service class: `com.artcraft.effectcraft.aiassistant.InferenceService`
- ABI: `arm64-v8a`
- Minimum Android version: Android 9 / API 28
- Inference: on-device llama.cpp; no cloud inference endpoint is used.

The companion contains the llama.cpp Android inference runtime. The DeepSeek model is downloaded once from the model manager and stored in the companion's app-private external-files directory. After the model download finishes, inference runs locally and can work without a network connection.

Model: DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS (GGUF, approximately 1.02 GB), from the bartowski model repository:
https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF

The embedded APK must be signed with the same persistent EffectCraft certificate as the host APK. The release workflow restores that key from the repository's Actions cache and verifies the certificate fingerprint before publishing.
