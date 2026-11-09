# EffectCraft DeepSeek AI Plugin

This is the companion APK for the EffectCraft Android host.

- Android package: `com.artcraft.effectcraft.aiassistant`
- Service action: `com.artcraft.effectcraft.aiassistant.BIND_INFERENCE`
- Service class: `com.artcraft.effectcraft.aiassistant.InferenceService`
- ABI: `arm64-v8a`
- Minimum Android version: Android 9 / API 28
- Inference: on-device llama.cpp; no cloud inference endpoint is used.

The plugin APK contains the llama.cpp Android inference runtime. The DeepSeek model is obtained once from the plugin's model manager and stored in the plugin's app-private external-files directory. After the model download finishes, inference runs locally and can work without a network connection.

Model: DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS (GGUF, approximately 1.02 GB), from the bartowski model repository:
https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF

The plugin must be signed with the same persistent EffectCraft certificate as the host APK. The release workflow restores that key from the repository's Actions cache and verifies the certificate fingerprint before publishing.
