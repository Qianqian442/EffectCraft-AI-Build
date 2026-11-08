package com.artcraft.effectcraft.aiassistant;

import android.app.Service;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Message;
import android.os.Messenger;
import android.os.IBinder;
import android.util.Log;

import java.io.File;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class InferenceService extends Service {
    public static final int MSG_GENERATE = 1;
    public static final int MSG_RESPONSE = 2;
    public static final int MSG_MODEL_STATUS = 3;
    public static final int MSG_MODEL_STATUS_RESULT = 4;

    private static final String TAG = "EffectCraftAIPlugin";
    private static final String MODEL_NAME = "DeepSeek-R1-Distill-Qwen-1.5B-IQ4_XS.gguf";
    private final ExecutorService inference = Executors.newSingleThreadExecutor();
    private Messenger messenger;

    static {
        System.loadLibrary("effectcraft_ai");
    }

    private static native String nativeGenerate(String modelPath, String prompt);
    private static native void nativeRelease();

    @Override
    public void onCreate() {
        super.onCreate();
        messenger = new Messenger(new Handler(Looper.getMainLooper(), this::handleMessage));
    }

    private boolean handleMessage(Message message) {
        Messenger reply = message.replyTo;
        if (reply == null) return true;

        if (message.what == MSG_MODEL_STATUS) {
            Bundle data = new Bundle();
            data.putBoolean("ready", isModelReady());
            Message response = Message.obtain(null, MSG_MODEL_STATUS_RESULT);
            response.setData(data);
            sendReply(reply, response);
            return true;
        }

        if (message.what == MSG_GENERATE) {
            Bundle request = message.getData();
            String requestId = request.getString("requestId", "");
            String prompt = request.getString("prompt", "");
            if (requestId.isEmpty() || prompt.trim().isEmpty()) return true;
            inference.execute(() -> {
                String output;
                if (!isModelReady()) {
                    output = "ERROR: 尚未准备 DeepSeek 模型。请在 AI 插件中下载或导入 GGUF 模型。";
                } else {
                    File model = modelFile();
                    try {
                        output = nativeGenerate(model.getAbsolutePath(), prompt);
                    } catch (Throwable error) {
                        output = "ERROR: 本地推理失败：" + safeMessage(error);
                    }
                    if (output == null) output = "ERROR: 本地推理没有返回内容。";
                }
                Bundle data = new Bundle();
                data.putString("requestId", requestId);
                data.putString("response", output);
                Message response = Message.obtain(null, MSG_RESPONSE);
                response.setData(data);
                sendReply(reply, response);
            });
            return true;
        }
        return true;
    }

    private File modelFile() {
        return new File(new File(getFilesDir(), "models"), MODEL_NAME);
    }

    private boolean isModelReady() {
        File model = modelFile();
        if (!model.isFile()) return false;
        long size = model.length();
        if (size < 950_000_000L || size > 1_100_000_000L) return false;
        try (java.io.RandomAccessFile input = new java.io.RandomAccessFile(model, "r")) {
            byte[] magic = new byte[4];
            input.readFully(magic);
            return magic[0] == 'G' && magic[1] == 'G' && magic[2] == 'U' && magic[3] == 'F';
        } catch (Exception ignored) {
            return false;
        }
    }

    private static void sendReply(Messenger target, Message message) {
        try {
            target.send(message);
        } catch (Exception error) {
            Log.w(TAG, "Could not return AI plugin response", error);
        }
    }

    private static String safeMessage(Throwable error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty()
            ? error.getClass().getSimpleName() : message;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return messenger.getBinder();
    }

    @Override
    public void onDestroy() {
        inference.execute(InferenceService::nativeRelease);
        inference.shutdown();
        super.onDestroy();
    }
}
