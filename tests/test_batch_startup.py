import os
import subprocess
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows batch files are only used on Windows")
class BatchStartupTest(unittest.TestCase):
    def test_batch_files_are_utf8_without_bom_and_use_only_crlf(self):
        for name in ("Cookie.bat", "Live.bat"):
            with self.subTest(name=name):
                content = (PROJECT_DIR / name).read_bytes()
                self.assertFalse(content.startswith(b"\xef\xbb\xbf"))
                self.assertEqual(content.count(b"\n"), content.count(b"\r\n"))
                content.decode("utf-8")

        attributes = (PROJECT_DIR / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.bat text eol=crlf", attributes.splitlines())

        live_script = (PROJECT_DIR / "Live.bat").read_text(encoding="utf-8")
        self.assertIn("--only-binary=:all:", live_script)
        self.assertIn("platform.python_version()", live_script)

    def test_cookie_check_mode_does_not_start_login(self):
        if not (PROJECT_DIR / "config.yml").is_file():
            self.skipTest("Worktree intentionally has no local config.yml")
        qrcode_path = PROJECT_DIR / "qrcode.png"
        qrcode_path.unlink(missing_ok=True)

        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "Cookie.bat", "--check"],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Cookie 获取工具环境验证成功", result.stdout)
        self.assertFalse(qrcode_path.exists())


if __name__ == "__main__":
    unittest.main()
