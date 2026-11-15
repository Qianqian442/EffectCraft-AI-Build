#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

__declspec(thread) static volatile LONG g_static_tls = 11;
static volatile LONG g_thread_result = 0;
static volatile LONG g_vectored_hits = 0;
static DWORD g_tls_index = TLS_OUT_OF_INDEXES;

typedef int (__cdecl *fixture_helper_fn)(void);

static int failures = 0;

#define CHECK(label, expression) do { \
    if (expression) { \
        printf("PASS: %s\n", label); \
    } else { \
        printf("FAIL: %s (GetLastError=%lu)\n", label, (unsigned long)GetLastError()); \
        ++failures; \
    } \
} while (0)

static LONG WINAPI vectored_handler(PEXCEPTION_POINTERS info) {
    if (info && info->ExceptionRecord &&
        info->ExceptionRecord->ExceptionCode == 0xEFC00001) {
        InterlockedIncrement(&g_vectored_hits);
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

static DWORD WINAPI worker_thread(LPVOID parameter) {
    uintptr_t expected = (uintptr_t)parameter;
    g_static_tls = 99;
    if (g_tls_index == TLS_OUT_OF_INDEXES ||
        !TlsSetValue(g_tls_index, (LPVOID)expected) ||
        TlsGetValue(g_tls_index) != (LPVOID)expected ||
        g_static_tls != 99) {
        InterlockedExchange(&g_thread_result, -1);
    } else {
        InterlockedExchange(&g_thread_result, 1);
    }
    return 0;
}

int main(void) {
    SYSTEM_INFO system_info;
    HMODULE helper_module;
    fixture_helper_fn helper;
    HANDLE thread;
    HANDLE file;
    PVOID memory;
    DWORD old_protect = 0;
    DWORD written = 0;
    DWORD read_count = 0;
    LARGE_INTEGER zero;
    char read_buffer[32] = {0};
    const char payload[] = "EffectCraft PE smoke";
    PVOID veh;

#ifdef _WIN64
    printf("ARCH=x86_64\n");
#else
    printf("ARCH=x86\n");
#endif

    GetSystemInfo(&system_info);
    printf("PAGE_SIZE=%lu\n", (unsigned long)system_info.dwPageSize);

    CHECK("PE image and static TLS initialized", g_static_tls == 11);

    helper_module = LoadLibraryW(L"fixture_helper.dll");
    CHECK("LoadLibraryW resolves dependent DLL", helper_module != NULL);
    helper = helper_module
        ? (fixture_helper_fn)GetProcAddress(helper_module, "fixture_helper_value")
        : NULL;
    CHECK("GetProcAddress resolves exported function", helper != NULL);
    if (helper) {
        CHECK("DLL static TLS and exported call execute", helper() == 0x123b);
    }

    g_tls_index = TlsAlloc();
    CHECK("TlsAlloc allocates a TLS slot", g_tls_index != TLS_OUT_OF_INDEXES);
    if (g_tls_index != TLS_OUT_OF_INDEXES) {
        CHECK("TlsSetValue stores main-thread TLS",
              TlsSetValue(g_tls_index, (LPVOID)(uintptr_t)0x1234));
        CHECK("TlsGetValue reads main-thread TLS",
              TlsGetValue(g_tls_index) == (LPVOID)(uintptr_t)0x1234);
        thread = CreateThread(NULL, 0, worker_thread, (LPVOID)(uintptr_t)0x5678, 0, NULL);
        CHECK("CreateThread starts a native Windows thread", thread != NULL);
        if (thread) {
            CHECK("WaitForSingleObject joins worker thread",
                  WaitForSingleObject(thread, 10000) == WAIT_OBJECT_0);
            CloseHandle(thread);
            CHECK("TLS is isolated between threads", g_thread_result == 1 &&
                  TlsGetValue(g_tls_index) == (LPVOID)(uintptr_t)0x1234 &&
                  g_static_tls == 11);
        }
        CHECK("TlsFree releases TLS slot", TlsFree(g_tls_index));
    }

    memory = VirtualAlloc(NULL, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    CHECK("VirtualAlloc reserves and commits memory", memory != NULL);
    if (memory) {
        memcpy(memory, "MEMORY-OK", 10);
        CHECK("VirtualProtect changes page protection",
              VirtualProtect(memory, 4096, PAGE_READONLY, &old_protect));
        CHECK("VirtualAlloc memory remains readable",
              memcmp(memory, "MEMORY-OK", 10) == 0);
        CHECK("VirtualFree releases mapping", VirtualFree(memory, 0, MEM_RELEASE));
    }

    veh = AddVectoredExceptionHandler(1, vectored_handler);
    CHECK("AddVectoredExceptionHandler registers handler", veh != NULL);
    if (veh) {
        RaiseException(0xEFC00001, 0, 0, NULL);
        CHECK("RaiseException reaches vectored handler", g_vectored_hits == 1);
        CHECK("RemoveVectoredExceptionHandler unregisters handler",
              RemoveVectoredExceptionHandler(veh) != 0);
    }

    file = CreateFileW(L"effectcraft-pe-smoke.tmp",
                       GENERIC_READ | GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                       FILE_ATTRIBUTE_NORMAL, NULL);
    CHECK("CreateFileW creates private working file", file != INVALID_HANDLE_VALUE);
    if (file != INVALID_HANDLE_VALUE) {
        CHECK("WriteFile writes test payload",
              WriteFile(file, payload, (DWORD)(sizeof(payload) - 1), &written, NULL) &&
              written == sizeof(payload) - 1);
        zero.QuadPart = 0;
        CHECK("SetFilePointerEx rewinds file", SetFilePointerEx(file, zero, NULL, FILE_BEGIN));
        CHECK("ReadFile reads test payload",
              ReadFile(file, read_buffer, sizeof(read_buffer) - 1, &read_count, NULL) &&
              read_count == sizeof(payload) - 1 &&
              memcmp(read_buffer, payload, sizeof(payload) - 1) == 0);
        CloseHandle(file);
        CHECK("DeleteFileW removes test file", DeleteFileW(L"effectcraft-pe-smoke.tmp"));
    }

    if (helper_module) {
        CHECK("FreeLibrary unloads dependent DLL", FreeLibrary(helper_module) != 0);
    }

    printf("FAILURES=%d\n", failures);
    printf("RESULT=%s\n", failures == 0 ? "PASS" : "FAIL");
    return failures == 0 ? 0 : 1;
}
