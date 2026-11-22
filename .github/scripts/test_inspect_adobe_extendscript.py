import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("inspect_adobe_extendscript.py")
SPEC = importlib.util.spec_from_file_location("inspect_adobe_extendscript", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExtendScriptStaticAnalysisTests(unittest.TestCase):
    def test_detects_ae_dom_but_ignores_comments_and_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.jsx"
            path.write_text(
                '// app.project.activeItem\n'
                'var note = "new Window";\n'
                'app.beginUndoGroup("Batch");\n'
                'var comp = app.project.activeItem;\n'
                'var win = new Window("palette");\n'
                'var file = new File("/tmp/a");\n',
                encoding="utf-8",
            )
            result = MODULE.inspect_jsx(path)
            groups = {item["capability"] for item in result["capabilities"]}
            self.assertIn("after_effects_project_dom", groups)
            self.assertIn("scriptui_panels", groups)
            self.assertIn("filesystem_access", groups)
            self.assertEqual(result["analysis_status"], "lexical_scan_only")
            self.assertFalse(result["execution_performed"])

    def test_detects_extend_script_directives_and_external_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "automation.jsx"
            path.write_text('#target aftereffects\nBridgeTalk.send();\nsystem.callSystem("echo hi");\n')
            result = MODULE.inspect_jsx(path)
            groups = {item["capability"] for item in result["capabilities"]}
            self.assertIn("extendscript_runtime_globals", groups)
            self.assertIn("external_process_or_bridge", groups)

    def test_rejects_jsxbin_and_oversized_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            compiled = Path(tmp) / "compiled.jsxbin"
            compiled.write_bytes(b"binary")
            with self.assertRaises(ValueError):
                MODULE.inspect_jsx(compiled)
            large = Path(tmp) / "large.jsx"
            with large.open("wb") as handle:
                handle.truncate(MODULE.MAX_SOURCE_BYTES + 1)
            with self.assertRaises(ValueError):
                MODULE.inspect_jsx(large)


if __name__ == "__main__":
    unittest.main()
