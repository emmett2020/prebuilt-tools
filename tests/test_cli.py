"""CLI helpers: arch detection and the error-note first-line guard."""
import unittest
from unittest import mock

from builder import __main__ as cli


class DetectArchTest(unittest.TestCase):
    def test_maps_uname_machine_to_canonical(self):
        for machine, expected in [("x86_64", "amd"), ("aarch64", "arm"),
                                  ("AMD64", "amd"), ("arm64", "arm")]:
            with mock.patch("platform.machine", return_value=machine):
                self.assertEqual(cli._detect_arch(), expected)

    def test_unknown_arch_exits(self):
        with mock.patch("platform.machine", return_value="riscv64"):
            with self.assertRaises(SystemExit):
                cli._detect_arch()


class FirstLineTest(unittest.TestCase):
    def test_empty_string_is_safe(self):
        self.assertEqual(cli._first_line(""), "")

    def test_takes_first_line(self):
        self.assertEqual(cli._first_line("boom\ndetails\nmore"), "boom")

    def test_truncates_to_limit(self):
        self.assertEqual(cli._first_line("x" * 500, limit=10), "x" * 10)


if __name__ == "__main__":
    unittest.main()
