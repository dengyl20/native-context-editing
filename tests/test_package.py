"""The package surface: ``import nce`` from the repository root.

The import must work with no third-party package installed, the version must
be declared, and every name re-exported by ``nce/__init__.py`` must resolve.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest

import context  # noqa: F401  (sets sys.path)

import nce

PACKAGE = os.path.dirname(os.path.abspath(nce.__file__))
ROOT = os.path.dirname(PACKAGE)


class ImportSurface(unittest.TestCase):
    def test_the_version_is_declared(self):
        self.assertTrue(isinstance(nce.__version__, str))
        parts = nce.__version__.split(".")
        self.assertGreaterEqual(len(parts), 2)
        for part in parts:
            self.assertTrue(part.isdigit(), part)

    def test_the_public_names_all_resolve(self):
        for name in nce.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(nce, name), name)

    def test_every_module_imports_on_its_own(self):
        modules = ["nce", "nce.tokens", "nce.grammar", "nce.state", "nce.runtime", "nce.render",
                   "nce.distill", "nce.annotate", "nce.annotate.audit", "nce.annotate.literals",
                   "nce.annotate.online", "nce.annotate.pipeline", "nce.annotate.release",
                   "nce.annotate.replay", "nce.annotate.rules", "nce.annotate.trajectory"]
        for name in modules:
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(name))

    def test_the_package_imports_without_third_party_packages(self):
        # A bare interpreter, no site-packages of the project, cwd elsewhere.
        script = (
            "import sys; sys.path.insert(0, %r); import nce; "
            "print(nce.__version__); print(len(nce.NCE_TOKENS))" % ROOT
        )
        result = subprocess.run([sys.executable, "-S", "-c", script],
                                capture_output=True, text=True, cwd="/")
        self.assertEqual(result.returncode, 0, result.stderr)
        version, count = result.stdout.split()
        self.assertEqual(version, nce.__version__)
        self.assertEqual(count, "70")

    def test_no_third_party_import_statements_in_the_package(self):
        allowed = {
            "__future__", "annotations", "dataclasses", "json", "re", "shutil", "typing",
            "collections", "functools", "itertools", "math", "os", "sys", "tempfile",
            "unittest", "abc",
        }
        import ast
        for dirpath, _dirs, files in os.walk(PACKAGE):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [a.name.split(".")[0] for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        if node.level:      # a relative import inside nce
                            continue
                        names = [(node.module or "").split(".")[0]]
                    else:
                        continue
                    for imported in names:
                        with self.subTest(file=os.path.relpath(path, ROOT), module=imported):
                            self.assertIn(imported, allowed, f"{imported} in {path}")
    def test_the_package_has_no_module_level_side_effects_beyond_the_tables(self):
        # Importing twice yields the same token table (the module-level assert
        # is a build-time check, not a mutation).
        first = list(nce.NCE_TOKENS)
        importlib.reload(importlib.import_module("nce.tokens"))
        second = list(importlib.import_module("nce.tokens").NCE_TOKENS)
        self.assertEqual(first, second)

    def test_the_readme_shape_expected_by_the_importers_is_present(self):
        # The names the examples and the docs use.
        for name in ("NCE_TOKENS", "encode_address", "decode_address", "parse_output",
                     "StreamParser", "State", "Runtime", "execute", "apply_output",
                     "render_text", "render_messages", "approx_tokens", "distill", "parse_envelope"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(nce, name), name)


if __name__ == "__main__":
    unittest.main()
