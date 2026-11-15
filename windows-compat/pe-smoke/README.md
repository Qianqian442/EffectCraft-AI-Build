# Windows PE runtime smoke fixtures

These are small, redistributable test fixtures for the Android ARM64 Hangover/Wine runtime.

The same source is cross-compiled into:

- x86/fixture_main.exe + x86/fixture_helper.dll (PE machine 0x014c)
- x86_64/fixture_main.exe + x86_64/fixture_helper.dll (PE machine 0x8664)

The fixture checks PE entry, static TLS, a dependent DLL, LoadLibraryW, GetProcAddress, CreateThread, dynamic TLS (TlsAlloc/TlsSetValue), VirtualAlloc/VirtualProtect, vectored exception dispatch, and file I/O. It prints one PASS line per check and exits nonzero on any failure.

## Reproducible cross-build

The CI workflow uses the pinned llvm-mingw 20250319 toolchain from the Termux Hangover recipe:

~~~sh
x86_64-w64-mingw32-clang -O2 -Wall -Wextra -Werror -shared -o x86_64/fixture_helper.dll fixture_helper.c
x86_64-w64-mingw32-clang -O2 -Wall -Wextra -Werror -o x86_64/fixture_main.exe fixture_main.c
i686-w64-mingw32-clang -O2 -Wall -Wextra -Werror -shared -o x86/fixture_helper.dll fixture_helper.c
i686-w64-mingw32-clang -O2 -Wall -Wextra -Werror -o x86/fixture_main.exe fixture_main.c
~~~

The build and PE audit are not execution tests. The Android M1/M2 test must run each executable on an ARM64 Android device under native-Bionic Hangover, from the directory containing its helper DLL, and capture stdout, exit code, Wine/Hangover logs, device model, Android build, kernel, and page size. Do not use a Windows computer as the runtime host for this test.
