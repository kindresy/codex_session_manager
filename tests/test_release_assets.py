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

    def test_ci_matrix(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        required = (
            "push:",
            "pull_request:",
            "fail-fast: false",
            "ubuntu-latest",
            "macos-latest",
            '"3.10"',
            '"3.11"',
            '"3.12"',
            '"3.13"',
            "actions/checkout@v4",
            "actions/setup-python@v5",
            "python -m unittest discover -s tests -v",
            "python -m compileall -q src tests",
            "python -m build",
            "pip install --no-deps dist/*.whl",
            "codex-session --help",
            "codex-session --version",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, workflow)

    def test_gitignore_release_artifacts(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        required = {
            ".venv/",
            "venv/",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
            ".coverage",
            "htmlcov/",
            "build/",
            "dist/",
            "*.egg-info/",
            "__pycache__/",
        }
        self.assertEqual(required - set(ignored), set())


if __name__ == "__main__":
    unittest.main()
