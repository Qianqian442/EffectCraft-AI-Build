from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class AdobePackageRoutingTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_android_incoming_intents_route_zxp_ccx(self):
        source = self.read("configure_android_storage_fallback.py")
        self.assertIn('matches!(extension.as_str(), "zxp" | "ccx")', source)
        self.assertIn('"aep", "aepx", "zip", "zxp", "ccx"', source)
        self.assertIn('"wasm", "wat", "jsx", "js", "aex", "dll", "ofx", "so", "dylib", "plugin", "bundle", "prm", "8bf"', source)

    def test_qq_picker_exposes_zxp_ccx(self):
        source = self.read("add_qq_plugin_import_support.py")
        self.assertIn('"zip" | "zxp" | "ccx"', source)
        self.assertIn("let name = entry.name();", source)
        self.assertIn("Tencent/QQfile_recv", source)

    def test_unified_import_picker_and_archive_handler_accept_zxp_ccx(self):
        picker = self.read("add_zip_plugin_support.py")
        package = self.read("add_desktop_plugin_package_support.py")
        self.assertIn('["zip", "zxp", "ccx"', picker)
        self.assertIn('"zip" | "zxp" | "ccx"', package)
        self.assertIn('original-package.{original_extension}', package)

    def test_other_options_route_catalog_is_scrollable_and_complete(self):
        source = self.read("add_plugin_migration_progress.py")
        self.assertIn('if *mode == MigrationMode::ManualBackend', source)
        self.assertIn('egui::ScrollArea::vertical()', source)
        self.assertIn('effectcraft-other-plugin-routes-scroll', source)
        self.assertIn('Wine64 + Box64', source)
        self.assertIn('Wine32 + Box86', source)
        self.assertIn('QEMU x86-64', source)
        self.assertIn('QEMU i386', source)
        self.assertIn('Remill + LLVM IR', source)
        self.assertIn('Ghidra 深度分析', source)
        self.assertIn('旧版系统与运行库兼容', source)
        self.assertIn('渲染兼容回退', source)
        self.assertIn('ui.button("取消")', source)
        self.assertIn('ui.button("按此方式开始")', source)


if __name__ == "__main__":
    unittest.main()
