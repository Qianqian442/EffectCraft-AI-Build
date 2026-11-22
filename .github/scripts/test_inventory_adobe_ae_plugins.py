import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).with_name("inventory_adobe_ae_plugins.py")
SPEC = importlib.util.spec_from_file_location("inventory_adobe_ae_plugins", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdobeAeInventoryTests(unittest.TestCase):
    def test_native_plugin_is_not_confused_with_project(self):
        self.assertEqual(MODULE.family_for("Plug-ins/Glow.aex"), "native_ae_plugin_candidate")
        self.assertEqual(MODULE.family_for("Project.aep"), "project_not_plugin")

    def test_script_and_preset_families(self):
        self.assertEqual(MODULE.family_for("Scripts/Batch.jsx"), "extendscript_or_compiled_extendscript")
        self.assertEqual(MODULE.family_for("Scripts/Compiled.jsxbin"), "extendscript_or_compiled_extendscript")
        self.assertEqual(MODULE.family_for("Presets/Zoom.ffx"), "animation_preset")

    def test_cep_and_uxp_are_distinct(self):
        self.assertEqual(MODULE.family_for("MyPanel.zxp"), "cep_extension_candidate")
        self.assertEqual(MODULE.family_for("MyPanel.ccx"), "uxp_extension_candidate")
        self.assertEqual(MODULE.family_for("CSXS/manifest.xml"), "cep_extension_candidate")

    def test_rejects_path_traversal(self):
        self.assertFalse(MODULE.safe_member("../escape.aex"))
        self.assertFalse(MODULE.safe_member("/absolute/plugin.aex"))
        self.assertFalse(MODULE.safe_member("folder\\\\plugin.aex"))
        self.assertTrue(MODULE.safe_member("Plug-ins/Glow.aex"))

    def test_zip_inventory_does_not_execute_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "sample.zxp"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("CSXS/manifest.xml", "<ExtensionManifest/>")
                zf.writestr("Plug-ins/Glow.aex", b"not executable here")
                zf.writestr("Scripts/Tool.jsx", "app.project.numItems;")
                zf.writestr("Project.aep", b"project")
                zf.writestr("../bad.aex", b"bad")
            result = MODULE.inspect_zip(archive)
            self.assertEqual(result["compatibility_status"], "inventory_only_not_executed")
            self.assertFalse(result["execution_performed"])
            self.assertEqual(result["counts"]["native_ae_plugin_candidate"], 1)
            self.assertEqual(result["counts"]["project_not_plugin"], 1)
            self.assertEqual(len(result["skipped"]), 1)

    def test_zxp_and_ccx_are_inspected_as_zip_archives_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            for suffix, expected in ((".zxp", "cep_extension_candidate"), (".ccx", "uxp_extension_candidate")):
                archive = Path(tmp) / f"extension{suffix}"
                with zipfile.ZipFile(archive, "w") as zf:
                    zf.writestr("manifest.json", '{"id":"example.panel","name":"Example"}')
                    zf.writestr("assets/panel.js", "/* package resource */")
                result = MODULE.inspect_zip(archive)
                self.assertEqual(result["compatibility_status"], "inventory_only_not_executed")
                self.assertFalse(result["execution_performed"])
                self.assertEqual(result["counts"][expected], 1)
                self.assertEqual(len(result["manifests"]), 1)
                self.assertTrue(result["manifests"][0]["valid_json"])


if __name__ == "__main__":
    unittest.main()
