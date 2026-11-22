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


if __name__ == "__main__":
    unittest.main()
