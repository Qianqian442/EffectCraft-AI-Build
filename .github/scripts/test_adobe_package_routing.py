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

    def test_qq_picker_exposes_zxp_ccx(self):
        source = self.read("add_qq_plugin_import_support.py")
        self.assertIn('"zip" | "zxp" | "ccx"', source)

    def test_unified_import_picker_and_archive_handler_accept_zxp_ccx(self):
        picker = self.read("add_zip_plugin_support.py")
        package = self.read("add_desktop_plugin_package_support.py")
        self.assertIn('["zip", "zxp", "ccx"', picker)
        self.assertIn('"zip" | "zxp" | "ccx"', package)
        self.assertIn('original-package.{original_extension}', package)


    def test_all_ae_native_plugin_suffixes_reach_the_native_import_pipeline(self):
        inventory = self.read("inventory_adobe_ae_plugins.py")
        package = self.read("add_desktop_plugin_package_support.py")
        migration = self.read("add_plugin_migration_progress.py")
        qq = self.read("add_qq_plugin_import_support.py")
        self.assertIn('".aex", ".pbk", ".pbg", ".8bi"', inventory)
        self.assertIn('"aex", "pbk", "pbg", "8bi"', package)
        self.assertIn('"aex", "pbk", "pbg", "8bi"', migration)
        self.assertIn('"pbk" | "pbg" | "8bi"', qq)

    def test_single_jsxbin_and_ffx_are_preserved_not_claimed_as_executable(self):
        migration = self.read("add_plugin_migration_progress.py")
        storage = self.read("configure_android_storage_fallback.py")
        package = self.read("add_desktop_plugin_package_support.py")
        self.assertIn('["jsxbin", "ffx"]', migration)
        self.assertIn('"jsxbin" | "ffx"', storage)
        self.assertIn('"zxp", "ccx", "ffx", "jsxbin"', package)
        self.assertIn("已归档，等待格式适配", migration)
        self.assertIn("归档不等于插件运行成功", migration)

    def test_zxp_and_ccx_are_sent_to_the_same_safe_archive_inspector(self):
        package = self.read("add_desktop_plugin_package_support.py")
        self.assertIn('matches!(extension.to_ascii_lowercase().as_str(), "zip" | "zxp" | "ccx")', package)

    def test_macos_plugin_bundle_resources_are_classified_as_native_candidates(self):
        inventory = self.read("inventory_adobe_ae_plugins.py")
        package = self.read("add_desktop_plugin_package_support.py")
        self.assertIn('part.lower().endswith((".plugin", ".bundle"))', inventory)
        self.assertIn('lower_path.contains(".plugin/")', package)
        self.assertIn('lower_path.contains(".bundle/")', package)


if __name__ == "__main__":
    unittest.main()
