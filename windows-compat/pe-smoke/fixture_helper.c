#include <windows.h>

__declspec(thread) static volatile LONG g_helper_tls = 7;

__declspec(dllexport) int __cdecl fixture_helper_value(void) {
    return 0x1234 + (int)g_helper_tls;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)instance;
    (void)reason;
    (void)reserved;
    return TRUE;
}
