package com.artcraft.effectcraft.aiassistant

import android.app.Activity
import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import java.io.File

class PluginManagerActivity : Activity() {
    private lateinit var statusText: TextView
    private lateinit var progressBar: ProgressBar
    private lateinit var downloadButton: Button
    private val handler = Handler(Looper.getMainLooper())
    private val preferences by lazy { getSharedPreferences("deepseek_plugin", Context.MODE_PRIVATE) }
    private val modelFile: File
        get() = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), MODEL_FILE)
    private val downloadManager by lazy { getSystemService(DownloadManager::class.java) }

    private val pollDownload = object : Runnable {
        override fun run() {
            val id = preferences.getLong(KEY_DOWNLOAD_ID, 0L)
            if (id == 0L) return
            val cursor = downloadManager.query(DownloadManager.Query().setFilterById(id))
            cursor.use {
                if (it == null || !it.moveToFirst()) {
                    statusText.text = "未找到下载任务，可重新开始下载。"
                    preferences.edit().remove(KEY_DOWNLOAD_ID).apply()
                    downloadButton.isEnabled = true
                    return
                }
                val status = it.getInt(it.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
                val downloaded = it.getLong(it.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
                val total = it.getLong(it.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
                if (total > 0L) {
                    val percent = ((downloaded * 100L) / total).toInt().coerceIn(0, 100)
                    progressBar.progress = percent
                    statusText.text = "正在下载 DeepSeek 本地模型：" + percent + "%（" +
                        formatBytes(downloaded) + " / " + formatBytes(total) + "）"
                } else {
                    statusText.text = "正在连接模型文件并下载… 已接收 " + formatBytes(downloaded)
                }

                when (status) {
                    DownloadManager.STATUS_SUCCESSFUL -> {
                        preferences.edit().remove(KEY_DOWNLOAD_ID).apply()
                        if (modelFile.isFile && modelFile.length() > MIN_MODEL_BYTES) {
                            progressBar.progress = 100
                            statusText.text = "DeepSeek 模型已准备完成。现在可以断网，在 EffectCraft 中使用本地 AI 助手。"
                            downloadButton.text = "模型已就绪"
                            downloadButton.isEnabled = false
                        } else {
                            statusText.text = "下载文件不完整，请删除后重新下载。"
                            modelFile.delete()
                            downloadButton.isEnabled = true
                        }
                        return
                    }
                    DownloadManager.STATUS_FAILED -> {
                        val reason = it.getInt(it.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON))
                        val usedMirror = preferences.getBoolean(KEY_USE_MIRROR, true)
                        preferences.edit().remove(KEY_DOWNLOAD_ID).apply()
                        modelFile.delete()
                        if (usedMirror) {
                            statusText.text = "国内镜像暂不可用（错误 " + reason + "），正在自动切换官方源…"
                            downloadButton.isEnabled = false
                            handler.postDelayed({ enqueueModelDownload(false) }, 1200L)
                        } else {
                            statusText.text = "镜像和官方源均下载失败（错误 " + reason + "）。请更换网络后重试。"
                            downloadButton.isEnabled = true
                        }
                        return
                    }
                    else -> handler.postDelayed(this, 1000L)
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildScreen()
        if (modelFile.isFile && modelFile.length() > MIN_MODEL_BYTES) {
            progressBar.progress = 100
            statusText.text = "DeepSeek 模型已准备完成。现在可以断网，在 EffectCraft 中使用本地 AI 助手。"
            downloadButton.text = "模型已就绪"
            downloadButton.isEnabled = false
        } else {
            statusText.text = "插件已安装。首次使用需要下载约 1.02 GB 的 DeepSeek 模型；下载完成后可离线推理。"
            handler.post(pollDownload)
        }
    }

    private fun buildScreen() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(24), dp(34), dp(24), dp(24))
        }
        root.addView(TextView(this).apply {
            text = "EffectCraft DeepSeek AI 插件"
            textSize = 22f
            gravity = Gravity.CENTER
        }, matchWidth())
        root.addView(TextView(this).apply {
            text = "独立本地推理引擎 · ARM64 · 无云端 API"
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, dp(18))
        }, matchWidth())
        statusText = TextView(this).apply {
            textSize = 15f
            gravity = Gravity.CENTER
        }
        root.addView(statusText, matchWidth())
        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progress = 0
        }
        root.addView(progressBar, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(10)).apply {
            topMargin = dp(20)
            bottomMargin = dp(20)
        })
        downloadButton = Button(this).apply {
            text = "下载 DeepSeek 本地模型（约 1.02 GB）"
            setOnClickListener { beginDownload() }
        }
        root.addView(downloadButton, matchWidth())
        root.addView(TextView(this).apply {
            text = "模型只下载一次并保存在本机应用私有目录。聊天推理在手机本地完成，不会把聊天内容发送到云端。"
            textSize = 13f
            gravity = Gravity.CENTER
            setPadding(0, dp(24), 0, 0)
        }, matchWidth())
        setContentView(root)
    }

    private fun beginDownload() {
        if (modelFile.isFile && modelFile.length() > MIN_MODEL_BYTES) {
            statusText.text = "模型已存在，可以离线使用。"
            downloadButton.isEnabled = false
            return
        }
        downloadButton.isEnabled = false
        progressBar.progress = 0
        statusText.text = "正在创建下载任务…"
        enqueueModelDownload(true)
    }

    private fun enqueueModelDownload(useMirror: Boolean) {
        val source = if (useMirror) MODEL_MIRROR_URL else MODEL_URL
        try {
            val request = DownloadManager.Request(Uri.parse(source))
                .setTitle("DeepSeek 本地模型")
                .setDescription(if (useMirror) "国内镜像优先 · EffectCraft 离线模型（约 1.02 GB）" else "官方源备用 · EffectCraft 离线模型（约 1.02 GB）")
                .setMimeType("application/octet-stream")
                .setAllowedOverMetered(true)
                .setAllowedOverRoaming(false)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalFilesDir(this, Environment.DIRECTORY_DOWNLOADS, MODEL_FILE)
            val id = downloadManager.enqueue(request)
            preferences.edit()
                .putLong(KEY_DOWNLOAD_ID, id)
                .putBoolean(KEY_USE_MIRROR, useMirror)
                .apply()
            statusText.text = if (useMirror) "正在尝试国内镜像下载 DeepSeek 模型…" else "正在切换 Hugging Face 官方源下载…"
            handler.removeCallbacks(pollDownload)
            handler.post(pollDownload)
        } catch (error: Exception) {
            statusText.text = "无法开始下载：" + (error.message ?: "未知错误")
            downloadButton.isEnabled = true
        }
    }

    override fun onResume() {
        super.onResume()
        if (::statusText.isInitialized && !isModelReady()) {
            handler.removeCallbacks(pollDownload)
            handler.post(pollDownload)
        }
    }

    override fun onDestroy() {
        handler.removeCallbacks(pollDownload)
        super.onDestroy()
    }

    private fun isModelReady() = modelFile.isFile && modelFile.length() > MIN_MODEL_BYTES
    private fun matchWidth() = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun formatBytes(value: Long): String = if (value >= 1024L * 1024L * 1024L) {
        "%.2f GB".format(value.toDouble() / (1024.0 * 1024.0 * 1024.0))
    } else {
        "%.0f MB".format(value.toDouble() / (1024.0 * 1024.0))
    }

    companion object {
        private const val MODEL_FILE = "DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf"
        private const val KEY_DOWNLOAD_ID = "model_download_id"
        private const val KEY_USE_MIRROR = "model_download_use_mirror"
        private const val MIN_MODEL_BYTES = 500L * 1024L * 1024L
        private const val MODEL_MIRROR_URL = "https://hf-mirror.com/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf?download=true"
        private const val MODEL_URL = "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf?download=true"
    }
}
