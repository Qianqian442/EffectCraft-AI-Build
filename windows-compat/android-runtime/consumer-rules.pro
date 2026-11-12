# Keep runtime entry points referenced by the native/plugin process bridge.
-keep class com.effectcraft.windowscompat.WindowsRuntimeSelector { *; }
-keep class com.effectcraft.windowscompat.RuntimeAssetInstaller { *; }
-keep class com.effectcraft.windowscompat.WinlatorBionicAssetCatalog { *; }
-keep class com.effectcraft.windowscompat.SafeRuntimeArchiveExtractor { *; }
