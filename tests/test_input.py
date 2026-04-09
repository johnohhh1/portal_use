"""
Unit tests for portal/input.py pure logic.
No libei, no hardware required.
"""
import sys
import os
import unittest

# Add parent dir so we can import portal.input without installing
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch ctypes before import so libei load doesn't fail in CI
import unittest.mock
with unittest.mock.patch("ctypes.CDLL"):
    with unittest.mock.patch("ctypes.util.find_library", return_value="libei.so.1"):
        from portal.input import KEY_CODES, _SHIFT_MAP


class TestKeyCodesCompleteness(unittest.TestCase):

    def test_all_lowercase_ascii_letters_present(self):
        for ch in "abcdefghijklmnopqrstuvwxyz":
            self.assertIn(ch, KEY_CODES, f"Missing: {ch!r}")

    def test_all_digits_present(self):
        for ch in "0123456789":
            self.assertIn(ch, KEY_CODES, f"Missing digit: {ch!r}")

    def test_common_punctuation_present(self):
        for ch in "`-=[]\\;',./":
            self.assertIn(ch, KEY_CODES, f"Missing punctuation: {ch!r}")

    def test_common_control_keys_present(self):
        for key in ("enter", "tab", "space", "backspace", "escape", "ctrl", "shift", "alt"):
            self.assertIn(key, KEY_CODES, f"Missing control key: {key!r}")

    def test_arrow_keys_present(self):
        for key in ("up", "down", "left", "right"):
            self.assertIn(key, KEY_CODES, f"Missing arrow: {key!r}")

    def test_function_keys_present(self):
        for i in range(1, 13):
            self.assertIn(f"f{i}", KEY_CODES, f"Missing: f{i}")


class TestShiftMap(unittest.TestCase):

    def test_shift_map_base_keys_exist_in_key_codes(self):
        """Every base key in _SHIFT_MAP must be in KEY_CODES."""
        for shifted, base in _SHIFT_MAP.items():
            self.assertIn(
                base, KEY_CODES,
                f"_SHIFT_MAP[{shifted!r}] = {base!r} but {base!r} not in KEY_CODES"
            )

    def test_common_shifted_symbols_covered(self):
        for ch in "!@#$%^&*()_+{}|:\"<>?~":
            self.assertIn(ch, _SHIFT_MAP, f"Missing shifted symbol: {ch!r}")


class TestTypeTextResolution(unittest.TestCase):
    """
    Test that type_text resolves characters correctly without hardware.
    We mock EIInput's key/button methods.
    """

    def _make_ei(self):
        """Return an EIInput with hardware calls patched out."""
        import unittest.mock
        with unittest.mock.patch("ctypes.CDLL"):
            with unittest.mock.patch("ctypes.util.find_library", return_value="libei.so.1"):
                from portal import input as inp
                obj = inp.EIInput.__new__(inp.EIInput)
                obj._fd = -1
                obj._width = 1920
                obj._height = 1080
                obj._ei = object()  # truthy
                obj._pointer_dev = object()
                obj._keyboard_dev = object()
                obj._seq = 0
                # Patch hardware calls
                obj.key = unittest.mock.MagicMock()
                return obj, inp

    def test_hello_world_no_error(self):
        ei, inp = self._make_ei()
        # Should not raise
        with unittest.mock.patch("time.sleep"):
            ei.type_text("hello world")

    def test_uppercase_no_error(self):
        ei, inp = self._make_ei()
        with unittest.mock.patch("time.sleep"):
            ei.type_text("Hello World")

    def test_common_punctuation_no_error(self):
        ei, inp = self._make_ei()
        with unittest.mock.patch("time.sleep"):
            ei.type_text("hello, world! foo@bar.com (test) http://x.com/path?q=1&r=2")

    def test_shell_command_no_error(self):
        ei, inp = self._make_ei()
        with unittest.mock.patch("time.sleep"):
            ei.type_text("ls -la ~/foo | grep '.py'")

    def test_unsupported_char_raises(self):
        ei, inp = self._make_ei()
        with unittest.mock.patch("time.sleep"):
            with self.assertRaises(ValueError) as ctx:
                ei.type_text("hello 🎉 world")
            self.assertIn("Cannot type", str(ctx.exception))

    def test_shift_symbols_call_shift_key(self):
        ei, inp = self._make_ei()
        calls = []
        ei.key = lambda code, pressed: calls.append((code, pressed))
        with unittest.mock.patch("time.sleep"):
            ei.type_text("!")
        # shift down, '1' down, '1' up, shift up
        shift_code = inp.KEY_CODES["shift"]
        one_code = inp.KEY_CODES["1"]
        self.assertEqual(calls[0], (shift_code, True))
        self.assertEqual(calls[1], (one_code, True))
        self.assertEqual(calls[2], (one_code, False))
        self.assertEqual(calls[3], (shift_code, False))


if __name__ == "__main__":
    unittest.main()
