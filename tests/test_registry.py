"""Recipe registry: discovery, lookup errors, duplicate/empty-name guards."""
import unittest
from pathlib import Path

from builder.core import recipe
from builder.core.recipe import Recipe, register


class _Dummy(Recipe):
    name = "llvm"  # collides with a real recipe on purpose

    def latest_version(self, channel):
        return ""

    def build(self, ctx):
        return Path(".")

    def package(self, ctx, install_prefix, out_dir):
        return []

    def smoke_test(self, ctx, install_prefix):
        pass


class RegistryTest(unittest.TestCase):
    def test_available_includes_real_recipes(self):
        names = recipe.available()
        self.assertIn("gcc", names)
        self.assertIn("llvm", names)
        self.assertIn("tree-sitter", names)

    def test_get_unknown_raises_systemexit(self):
        with self.assertRaises(SystemExit):
            recipe.get("does-not-exist")

    def test_get_known_returns_instance(self):
        self.assertEqual(recipe.get("llvm").name, "llvm")

    def test_duplicate_name_rejected(self):
        recipe.available()  # ensure real recipes are loaded/registered
        with self.assertRaises(ValueError):
            register(_Dummy())

    def test_empty_name_rejected(self):
        class _NoName(_Dummy):
            name = ""
        with self.assertRaises(ValueError):
            register(_NoName())


if __name__ == "__main__":
    unittest.main()
