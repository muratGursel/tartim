"""Validity of the configuration files in the repository. GitHub silently ignores
a broken template; this test catches that early."""

import unittest
from pathlib import Path

try:
    import yaml

    if not hasattr(yaml, "safe_load"):  # another module with the same name
        yaml = None
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(yaml, "PyYAML gerekli (python3-yaml)")
class YamlFilesTests(unittest.TestCase):
    def test_yaml_files_parse(self):
        for path in sorted((ROOT / ".github").rglob("*.yml")):
            with self.subTest(path=path.name):
                self.assertIsInstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict)

    def test_issue_form_has_required_keys(self):
        form = yaml.safe_load((ROOT / ".github/ISSUE_TEMPLATE/cihaz-raporu.yml")
                              .read_text(encoding="utf-8"))
        for key in ("name", "description", "body"):
            self.assertIsInstance(form[key], (str, list), key)
        ids = [item.get("id") for item in form["body"] if item["type"] != "markdown"]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
