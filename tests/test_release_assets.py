import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseAssetTests(unittest.TestCase):
    def test_project_metadata(self):
        metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        required = (
            'readme = "README.md"',
            'license = "MIT"',
            'license-files = ["LICENSE"]',
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
        self.assertNotIn('"License :: OSI Approved :: MIT License"', metadata)

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

    def test_standalone_build_assets(self):
        requirements = (
            ROOT / "packaging/requirements-standalone.txt"
        ).read_text(encoding="utf-8")
        for pin in (
            "PyInstaller==6.21.0",
            "altgraph==0.17.5",
            "packaging==26.3",
            "pyinstaller-hooks-contrib==2026.7",
            "setuptools==65.5.1",
        ):
            self.assertIn(pin, requirements)
        spec = (ROOT / "packaging/codex-session.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn("src/codex_session_manager/__main__.py", spec)
        self.assertIn('name="codex-session"', spec)
        self.assertIn('name="codex-session-manager"', spec)
        build = (ROOT / "scripts/build-standalone.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("python -m unittest discover -s tests -v", build)
        self.assertIn("python -m PyInstaller", build)
        self.assertIn("tests/verify_standalone.py", build)
        self.assertIn("sha256sum", build)

    def test_linux_standalone_release_workflow(self):
        workflow = (
            ROOT / ".github/workflows/release-linux-x86_64.yml"
        ).read_text(encoding="utf-8")
        required = (
            "pull_request:",
            "workflow_dispatch:",
            "linux-x86_64-release",
            "4e96d6c7c610e5b2a46ff8a36cc76a159d57a5b865d580eda29d51afdc1a1923",
            'ubuntu: ["20.04", "22.04", "24.04"]',
            "scripts/build-standalone.sh",
            "scripts/test-standalone.sh",
            "actions/upload-artifact@v4",
            "actions/download-artifact@v4",
            "contents: write",
            "gh release create",
            "--draft",
            "gh release edit",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, workflow)

    def test_sdist_manifest_and_distribution_checks(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("include .gitignore", manifest)
        self.assertIn("include .github/workflows/ci.yml", manifest)
        self.assertIn("recursive-include tests *.py *.sql *.jsonl", manifest)

        verifier = ROOT / "tests" / "verify_distribution.py"
        self.assertTrue(verifier.is_file())
        verifier_text = verifier.read_text(encoding="utf-8")
        self.assertIn("Description-Content-Type: text/markdown", verifier_text)
        self.assertIn("tests/fixtures/current_schema.sql", verifier_text)

        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("python tests/verify_distribution.py", workflow)
        self.assertIn("sdist-test/codex_session_manager-0.1.0", workflow)
        self.assertIn(
            "include .github/workflows/release-linux-x86_64.yml", manifest
        )
        self.assertIn("recursive-include packaging *.spec *.txt", manifest)
        self.assertIn("recursive-include scripts *.sh", manifest)

    def test_readme_public_usage(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        required = (
            "Linux",
            "macOS",
            "WSL",
            "原生 Windows",
            "Python 3.10",
            "UTF-8",
            "curses",
            "https://github.com/kindresy/codex_session_manager.git",
            "git clone",
            "python3 -m venv .venv",
            "python3 -m pip install .",
            'python3 -m pip install "git+https://github.com/kindresy/codex_session_manager.git"',
            "PYTHONPATH=src python3 -m codex_session_manager",
            "python3 -m pip install -e .",
            "$CODEX_HOME",
            "--codex-home",
            "只读",
            "内部格式",
            "找不到 codex",
            "没有找到可恢复",
            "codex --version",
            "python3 --version",
            "codex-session --version",
            "Ctrl-d",
            "Ctrl-u",
            "Enter",
            "搜索首问、完整 session ID 和工作目录",
            "不扫描完整会话内容",
            "不区分大小写",
            "`n` / `N`",
            "codex-session-manager-linux-x86_64.tar.gz",
            "releases/latest/download/install.sh",
            "bash install.sh",
            "--prefix",
            "--version",
            "~/.local/bin",
            "无需安装或升级 Python",
            "升级",
            "回退",
            "卸载",
            "glibc 2.31",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, readme)


if __name__ == "__main__":
    unittest.main()
