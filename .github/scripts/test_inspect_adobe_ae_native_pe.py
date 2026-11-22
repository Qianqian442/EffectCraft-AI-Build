import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("inspect_adobe_ae_native_pe.py")
SPEC = importlib.util.spec_from_file_location("inspect_adobe_ae_native_pe", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_minimal_pe(machine=0x8664, magic=0x20B):
    data = bytearray(512)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    coff = 0x84
    struct.pack_into("<HHIIIHH", data, coff, machine, 1, 0, 0, 0, 112 if magic == 0x20B else 96, 0)
    optional = coff + 20
    struct.pack_into("<H", data, optional, magic)
    # No data directories, one small section at raw offset 0x200.
    number_offset = optional + (108 if magic == 0x20B else 92)
    struct.pack_into("<I", data, number_offset, 0)
    section = optional + (112 if magic == 0x20B else 96)
    data[section:section + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", data, section + 8, 16, 0x1000, 16, 0x200)
    return bytes(data)


class AdobeAeNativePeTests(unittest.TestCase):
    def test_inspects_x64_pe_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Glow.aex"
            path.write_bytes(make_minimal_pe())
            result = MODULE.inspect_pe(path)
            self.assertEqual(result["format"], "PE")
            self.assertEqual(result["machine"], "x86_64")
            self.assertEqual(result["bitness"], 64)
            self.assertFalse(result["execution_performed"])
            self.assertEqual(result["compatibility_status"], "static_analysis_only")

    def test_inspects_x86_pe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Legacy.aex"
            path.write_bytes(make_minimal_pe(0x014C, 0x10B))
            result = MODULE.inspect_pe(path)
            self.assertEqual(result["machine"], "x86")
            self.assertEqual(result["bitness"], 32)

    def test_rejects_non_pe_and_truncated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.aex"
            path.write_bytes(b"not a PE")
            result = MODULE.inspect_pe(path)
            self.assertIn("error", result)

    def test_rejects_oversized_binary_before_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oversized.aex"
            with path.open("wb") as handle:
                handle.truncate(MODULE.MAX_FILE_BYTES + 1)
            with self.assertRaises(MODULE.PEError):
                MODULE.inspect_pe(path)


if __name__ == "__main__":
    unittest.main()
