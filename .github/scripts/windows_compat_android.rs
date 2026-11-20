//! JNI bridge for the optional Windows x86/x64 compatibility runtime.
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

#[cfg(target_os = "android")]
static ANDROID_VM_PTR: AtomicUsize = AtomicUsize::new(0);
static NEXT_REQUEST: AtomicU64 = AtomicU64::new(1);

#[cfg(target_os = "android")]
pub(crate) fn init_android_vm(ptr: *mut std::ffi::c_void) {
    ANDROID_VM_PTR.store(ptr as usize, Ordering::Release);
}

#[cfg(target_os = "android")]
fn with_android_vm<T>(
    f: impl FnOnce(&jni::vm::JavaVM) -> Result<T, String>,
) -> Result<T, String> {
    let raw_vm = ANDROID_VM_PTR.load(Ordering::Acquire) as *mut jni::sys::JavaVM;
    if raw_vm.is_null() {
        return Err("Windows 兼容运行时 JNI 尚未初始化。".into());
    }
    // android_app.vm_as_ptr() provides the process-owned JavaVM pointer.
    // Wrap that exact pointer instead of relying on jni-rs' per-crate singleton,
    // which may not have been initialized by a different android-activity build.
    let vm = unsafe { jni::vm::JavaVM::from_raw(raw_vm) };
    f(&vm)
}

#[cfg(target_os = "android")]
pub(crate) fn start_runtime_install() -> Result<String, String> {
    let request_id = format!(
        "windows-runtime-{}",
        NEXT_REQUEST.fetch_add(1, Ordering::Relaxed)
    );
    with_android_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let class = env.load_class(jni::jni_str!("com.artcraft.effectcraft.WindowsCompatAndroidBridge"))?;
            let id = env.new_string(&request_id)?;
            env.call_static_method(
                &class,
                jni::jni_str!("startRuntimeInstall"),
                jni::jni_sig!("(Ljava/lang/String;)V"),
                &[jni::objects::JValue::Object(&id)],
            )?;
            Ok(())
        }).map_err(|error| error.to_string())
    })?;
    Ok(request_id)
}

#[cfg(target_os = "android")]
pub(crate) fn start_aex_plugin_test(source_path: &str) -> Result<String, String> {
    let request_id = format!(
        "aex-test-{}",
        NEXT_REQUEST.fetch_add(1, Ordering::Relaxed)
    );
    with_android_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<()> {
            let class = env.load_class(jni::jni_str!("com.artcraft.effectcraft.WindowsCompatAndroidBridge"))?;
            let id = env.new_string(&request_id)?;
            let path = env.new_string(source_path)?;
            env.call_static_method(
                &class,
                jni::jni_str!("startAexPluginTest"),
                jni::jni_sig!("(Ljava/lang/String;Ljava/lang/String;)V"),
                &[jni::objects::JValue::Object(&id), jni::objects::JValue::Object(&path)],
            )?;
            Ok(())
        }).map_err(|error| error.to_string())
    })?;
    Ok(request_id)
}

#[cfg(target_os = "android")]
pub(crate) fn poll_runtime_install(request_id: &str) -> Result<Option<String>, String> {
    with_android_vm(|vm| {
        vm.attach_current_thread(|env| -> jni::errors::Result<Option<String>> {
            let class = env.load_class(jni::jni_str!("com.artcraft.effectcraft.WindowsCompatAndroidBridge"))?;
            let id = env.new_string(request_id)?;
            let object = env.call_static_method(
                &class,
                jni::jni_str!("pollRuntimeInstall"),
                jni::jni_sig!("(Ljava/lang/String;)Ljava/lang/String;"),
                &[jni::objects::JValue::Object(&id)],
            )?.l()?;
            if object.is_null() {
                return Ok(None);
            }
            let result = env.as_cast::<jni::objects::JString>(&object)?;
            Ok(Some(result.to_string()))
        }).map_err(|error| error.to_string())
    })
}

#[cfg(not(target_os = "android"))]
pub(crate) fn init_android_vm(_ptr: *mut std::ffi::c_void) {}

#[cfg(not(target_os = "android"))]
pub(crate) fn start_runtime_install() -> Result<String, String> {
    Err("电脑版 Windows 兼容运行环境仅在 Android 版中安装。".into())
}

#[cfg(not(target_os = "android"))]
pub(crate) fn poll_runtime_install(_request_id: &str) -> Result<Option<String>, String> {
    Ok(None)
}

#[cfg(not(target_os = "android"))]
pub(crate) fn start_aex_plugin_test(_source_path: &str) -> Result<String, String> {
    Err("Windows x86/x64 原生插件测试仅在 Android 版中运行。".into())
}
