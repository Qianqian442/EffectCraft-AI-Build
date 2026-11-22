import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("inspect_adobe_ffx_preset.py")
SPEC = importlib.util.spec_from_file_location("inspect_adobe_ffx_preset", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdobeFfxReadOnlyTests(unittest.TestCase):
    def test_inspects_strings_without_claiming_format_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.ffx"
            path.write_bytes(b"\x00\x01Adobe After Effects\x00Effect\x00Keyframe\x00")
            result = MODULE.inspect_ffx(path)
            self.assertEqual(result["format_status"], "opaque_binary_unparsed")
            self.assertEqual(result["translation_status"], "not_implemented")
            self.assertIn("adobe", result["heuristic_indicators"])
            self.assertFalse(result["execution_performed"])
            self.assertFalse(result["input_modified"])
            self.assertEqual(len(result["sha256"]), 64)

    def test_rejects_wrong_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.bin"
            path.write_bytes(b"data")
            with self.assertRaises(ValueError):
                MODULE.inspect_ffx(path)

    def test_rejects_oversized_preset_before_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.ffx"
            with path.open("wb") as handle:
                handle.truncate(MODULE.MAX_FILE_BYTES + 1)
            with self.assertRaises(ValueError):
                MODULE.inspect_ffx(path)


if __name__ == "__main__":
    unittest.main()
