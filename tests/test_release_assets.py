import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseAssetTests(unittest.TestCase):
    def test_project_metadata(self):
        metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        required = (
            'readme = "README.md"',
            'license = { file = "LICENSE" }',
            'authors = [{ name = "kindresy" }]',
            'dependencies = []',
            '"Operating System :: MacOS"',
            '"Operating System :: POSIX :: Linux"',
            '"Programming Language :: Python :: 3.10"',
            '"Programming Language :: Python :: 3.11"',
            '"Programming Language :: Python :: 3.12"',
            '"Programming Language :: Python :: 3.13"',
            'Homepage = "https://github.com/kindresy/codex_session_manager"',
            'Repository = "https://github.com/kindresy/codex_session_manager"',
            'Issues = "https://github.com/kindresy/codex_session_manager/issues"',
            'include-package-data = false',
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, metadata)

    def test_mit_license(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 kindresy", license_text)
        self.assertIn("Permission is hereby granted, free of charge", license_text)
        self.assertIn("THE SOFTWARE IS PROVIDED \"AS IS\"", license_text)


if __name__ == "__main__":
    unittest.main()
