package com.artcraft.effectcraft.aiassistant

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.Message
import android.os.Messenger
import android.os.IBinder
import com.arm.aichat.AiChat
import com.arm.aichat.InferenceEngine
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class InferenceService : Service() {
    private val inferenceExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private lateinit var messenger: Messenger

    override fun onCreate() {
        super.onCreate()
        messenger = Messenger(IncomingHandler())
    }

    override fun onBind(intent: Intent?): IBinder = messenger.binder

    override fun onDestroy() {
        inferenceExecutor.shutdownNow()
        super.onDestroy()
    }

    private inner class IncomingHandler : Handler(Looper.getMainLooper()) {
        override fun handleMessage(message: Message) {
            if (message.what != AI_GENERATE) {
                super.handleMessage(message)
                return
            }
            val requestId = message.data.getString("requestId").orEmpty()
            val prompt = message.data.getString("prompt").orEmpty()
            val replyTo = message.replyTo
            if (requestId.isBlank() || prompt.isBlank() || replyTo == null) return

            inferenceExecutor.execute {
                val result = try {
                    runBlocking(Dispatchers.IO) { infer(prompt) }
                } catch (error: Exception) {
                    "ERROR: 本地 DeepSeek 推理失败：" + (error.message ?: error.javaClass.simpleName)
                }
                val response = Message.obtain(null, AI_RESPONSE)
                response.data = Bundle().apply {
                    putString("requestId", requestId)
                    putString("response", result)
                }
                try {
                    replyTo.send(response)
                } catch (_: Exception) {
                    // The EffectCraft host may have closed its chat panel.
                }
            }
        }
    }

    private suspend fun infer(prompt: String): String {
        val model = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), MODEL_FILE)
        if (!model.isFile || model.length() < MIN_MODEL_BYTES) {
            throw IllegalStateException("请先打开“EffectCraft DeepSeek AI 插件”，下载约 1.02 GB 的本地模型。")
        }

        val engine = AiChat.getInferenceEngine(applicationContext)
        val initialized = withTimeout(180_000L) {
            engine.state.first {
                it is InferenceEngine.State.Initialized ||
                    it is InferenceEngine.State.ModelReady ||
                    it is InferenceEngine.State.Error
            }
        }
        if (initialized is InferenceEngine.State.Error) {
            throw initialized.exception
        }
        if (initialized is InferenceEngine.State.Initialized) {
            engine.loadModel(model.absolutePath)
            engine.setSystemPrompt(
                "你是 EffectCraft 0.21.1 中文操作助手。用简体中文回答，优先给出准确菜单路径和分步操作；没有依据时明确说不知道，不要编造。你熟悉素材导入、时间轴、合成、图层、关键帧、效果、项目导入导出和视频导出。"
            )
        }
        return engine.sendUserPrompt(prompt, predictLength = 256).toList().joinToString("").trim()
            .ifEmpty { "模型没有生成可显示的回答，请换一种问法。" }
    }

    companion object {
        private const val AI_GENERATE = 1
        private const val AI_RESPONSE = 2
        private const val MODEL_FILE = "DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf"
        private const val MIN_MODEL_BYTES = 500L * 1024L * 1024L
    }
}
