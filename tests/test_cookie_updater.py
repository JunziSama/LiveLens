import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

import cookie_updater


class TtyBuffer(io.StringIO):
    def isatty(self):
        return True


def api_response(data, status_code=200, content_type="application/json"):
    response = Mock()
    response.status_code = status_code
    response.headers = {"Content-Type": content_type}
    response.json.return_value = {"code": 0, "data": data}
    response.cookies.get_dict.return_value = {}
    return response


class ConsoleQrCodeTest(unittest.TestCase):
    def test_console_qrcode_does_not_reveal_login_url(self):
        secret_url = "https://example.invalid/login?secret=do-not-print"
        qr = cookie_updater.build_qrcode(secret_url)
        output = TtyBuffer()
        opener = Mock()

        rendered = cookie_updater.display_qrcode(
            qr,
            "qrcode.png",
            output=output,
            interactive=True,
            image_opener=opener,
            terminal_columns=200,
        )

        self.assertTrue(rendered)
        self.assertIn("█", output.getvalue())
        self.assertNotIn("▀", output.getvalue())
        self.assertNotIn("▄", output.getvalue())
        self.assertNotIn(secret_url, output.getvalue())
        self.assertNotIn("do-not-print", output.getvalue())
        opener.assert_not_called()

    def test_full_block_renderer_preserves_square_modules(self):
        qr = Mock()
        qr.get_matrix.return_value = [[False, True], [True, False]]
        output = io.StringIO()

        rendered, required_columns = cookie_updater._render_console_qrcode(
            qr,
            output,
            terminal_columns=4,
        )

        self.assertTrue(rendered)
        self.assertEqual(required_columns, 4)
        self.assertEqual(output.getvalue(), "██  \n  ██\n")

    def test_narrow_console_is_resized_before_rendering(self):
        qr = cookie_updater.build_qrcode(
            "https://example.invalid/login?payload=" + "x" * 160
        )
        required_columns = len(qr.get_matrix()[0]) * 2
        self.assertGreater(required_columns, 101)
        output = TtyBuffer()
        opener = Mock()
        resizer = Mock(return_value=max(120, required_columns))

        rendered = cookie_updater.display_qrcode(
            qr,
            "qrcode.png",
            output=output,
            interactive=True,
            image_opener=opener,
            terminal_columns=101,
            console_resizer=resizer,
        )

        self.assertTrue(rendered)
        resizer.assert_called_once_with(required_columns)
        self.assertIn("█", output.getvalue())
        opener.assert_not_called()

    def test_windows_console_resize_targets_at_least_120_columns(self):
        size_getter = Mock(side_effect=[101, 120])
        completed = Mock(returncode=0)

        with (
            patch("cookie_updater.os.name", "nt"),
            patch("cookie_updater.subprocess.run", return_value=completed) as runner,
        ):
            columns = cookie_updater._resize_windows_console(
                114,
                terminal_size_getter=size_getter,
            )

        self.assertEqual(columns, 120)
        runner.assert_called_once_with(
            ["cmd.exe", "/d", "/c", "mode con cols=120"],
            stdout=cookie_updater.subprocess.DEVNULL,
            stderr=cookie_updater.subprocess.DEVNULL,
            check=False,
        )

    def test_resize_failure_only_prints_manual_fallback_instructions(self):
        qr = cookie_updater.build_qrcode(
            "https://example.invalid/login?payload=" + "x" * 160
        )
        output = TtyBuffer()
        opener = Mock()
        resizer = Mock(return_value=101)

        rendered = cookie_updater.display_qrcode(
            qr,
            "qrcode.png",
            output=output,
            interactive=True,
            image_opener=opener,
            terminal_columns=101,
            console_resizer=resizer,
        )

        self.assertFalse(rendered)
        self.assertIn("控制台宽度不足", output.getvalue())
        self.assertIn("按 R 重新绘制", output.getvalue())
        self.assertIn("按 O 打开备用图片", output.getvalue())
        self.assertNotIn("█", output.getvalue())
        opener.assert_not_called()

    def test_noninteractive_console_never_opens_fallback_image(self):
        qr = cookie_updater.build_qrcode("https://example.invalid/login")
        output = io.StringIO()
        opener = Mock()

        cookie_updater.display_qrcode(
            qr,
            "qrcode.png",
            output=output,
            interactive=False,
            image_opener=opener,
            terminal_columns=200,
        )

        opener.assert_not_called()

    def test_render_failure_does_not_open_fallback_image(self):
        qr = Mock()
        qr.get_matrix.side_effect = UnicodeError("unsupported console")
        output = TtyBuffer()
        opener = Mock()

        rendered = cookie_updater.display_qrcode(
            qr,
            "qrcode.png",
            output=output,
            interactive=True,
            image_opener=opener,
            terminal_columns=200,
        )

        self.assertFalse(rendered)
        opener.assert_not_called()


class LoginPollingTest(unittest.TestCase):
    def make_session(self):
        session = Mock()
        session.cookies.get_dict.return_value = {}
        return session

    def test_network_failure_recovers_and_o_opens_viewer(self):
        session = self.make_session()
        waiting = api_response({"code": 86101, "message": "waiting"})
        success = api_response({"code": 0, "message": "ok"})
        success.cookies.get_dict.return_value = {
            "SESSDATA": "session",
            "bili_jct": "csrf",
            "DedeUserID": "123",
        }
        opener = Mock()

        with patch(
            "cookie_updater.util.requests_get",
            side_effect=[None, waiting, success],
        ):
            result = cookie_updater.poll_login(
                session,
                "temporary-key",
                "qrcode.png",
                key_reader=Mock(side_effect=["o", None, None]),
                image_opener=opener,
                clock=lambda: 0,
                sleeper=Mock(),
            )

        self.assertEqual(result, ("session", "csrf", "123"))
        opener.assert_called_once_with("qrcode.png")

    def test_r_redraws_same_qrcode_without_resetting_poll(self):
        session = self.make_session()
        success = api_response({"code": 0, "message": "ok"})
        success.cookies.get_dict.return_value = {
            "SESSDATA": "session",
            "bili_jct": "csrf",
            "DedeUserID": "123",
        }
        redraw = Mock()

        with patch("cookie_updater.util.requests_get", return_value=success):
            result = cookie_updater.poll_login(
                session,
                "temporary-key",
                "qrcode.png",
                key_reader=Mock(side_effect=["r"]),
                redraw_callback=redraw,
                clock=lambda: 0,
                sleeper=Mock(),
            )

        self.assertEqual(result, ("session", "csrf", "123"))
        redraw.assert_called_once_with()

    def test_expired_qrcode_raises_specific_error(self):
        session = self.make_session()
        expired = api_response({"code": 86038, "message": "expired"})
        with patch("cookie_updater.util.requests_get", return_value=expired):
            with self.assertRaises(cookie_updater.LoginExpiredError):
                cookie_updater.poll_login(
                    session,
                    "temporary-key",
                    "qrcode.png",
                    key_reader=lambda: None,
                    clock=lambda: 0,
                    sleeper=Mock(),
                )

    def test_scanned_state_continues_until_success(self):
        session = self.make_session()
        scanned = api_response({"code": 86090, "message": "scanned"})
        success = api_response({"code": 0, "message": "ok"})
        success.cookies.get_dict.return_value = {
            "SESSDATA": "session",
            "bili_jct": "csrf",
            "DedeUserID": "123",
        }

        with patch(
            "cookie_updater.util.requests_get",
            side_effect=[scanned, success],
        ):
            result = cookie_updater.poll_login(
                session,
                "temporary-key",
                "qrcode.png",
                key_reader=lambda: None,
                clock=lambda: 0,
                sleeper=Mock(),
            )

        self.assertEqual(result, ("session", "csrf", "123"))

    def test_continuous_network_failure_ends_at_deadline(self):
        session = self.make_session()
        clock = Mock(side_effect=[0, 0, 2])
        with patch("cookie_updater.util.requests_get", return_value=None):
            with self.assertRaises(cookie_updater.LoginTimeoutError):
                cookie_updater.poll_login(
                    session,
                    "temporary-key",
                    "qrcode.png",
                    timeout=1,
                    poll_interval=0,
                    key_reader=lambda: None,
                    clock=clock,
                    sleeper=Mock(),
                )

    def test_412_and_non_json_are_recoverable(self):
        blocked = api_response({}, status_code=412, content_type="text/html")
        html = api_response({}, content_type="text/html")

        self.assertIsNone(cookie_updater._response_json(blocked, "测试"))
        self.assertIsNone(cookie_updater._response_json(html, "测试"))
        blocked.json.assert_not_called()
        html.json.assert_not_called()


class AtomicConfigUpdateTest(unittest.TestCase):
    VALID_COOKIE = "SESSDATA=session; bili_jct=csrf; DedeUserID=123"
    CONFIG = """common: {}
query_task:
  - name: renamed-task
    type: bilibili
    uid_list:
      - "10001"
      - "10002"
    target_push_name_list:
      - channel-a
    mute_time_ranges_live:
      - start: "00:00"
        end: "01:00"
    cookie: "old"  # keep-this-comment
  - name: another-task
    type: douyu
    cookie: "untouched"
push_channel: []
"""

    def test_updates_task_by_type_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yml"
            backup_path = Path(directory) / "config.yml.bak"
            config_path.write_text(self.CONFIG, encoding="utf-8")

            result = cookie_updater.update_cookie_in_file(
                self.VALID_COOKIE,
                config_path=config_path,
                backup_path=backup_path,
            )

            self.assertEqual(result, backup_path)
            self.assertEqual(backup_path.read_text(encoding="utf-8"), self.CONFIG)
            updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["query_task"][0]["cookie"], self.VALID_COOKIE)
            self.assertEqual(updated["query_task"][1]["cookie"], "untouched")
            self.assertIn("# keep-this-comment", config_path.read_text(encoding="utf-8"))

    def test_crlf_is_preserved_when_updating_nested_task(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yml"
            crlf_config = self.CONFIG.replace("\n", "\r\n")
            config_path.write_bytes(crlf_config.encode("utf-8"))

            cookie_updater.update_cookie_in_file(
                self.VALID_COOKIE,
                config_path=config_path,
            )

            updated = config_path.read_bytes()
            self.assertEqual(updated.count(b"\n"), updated.count(b"\r\n"))
            self.assertIn(b"# keep-this-comment", updated)

    def test_missing_or_duplicate_cookie_leaves_original_unchanged(self):
        invalid_configs = (
            self.CONFIG.replace('    cookie: "old"  # keep-this-comment\n', ""),
            self.CONFIG.replace(
                '    cookie: "old"  # keep-this-comment\n',
                '    cookie: "old"\n    cookie: "duplicate"\n',
            ),
        )
        for invalid_config in invalid_configs:
            with self.subTest():
                with tempfile.TemporaryDirectory() as directory:
                    config_path = Path(directory) / "config.yml"
                    config_path.write_text(invalid_config, encoding="utf-8")

                    with self.assertRaises(cookie_updater.CookieUpdaterError):
                        cookie_updater.update_cookie_in_file(
                            self.VALID_COOKIE,
                            config_path=config_path,
                        )

                    self.assertEqual(
                        config_path.read_text(encoding="utf-8"),
                        invalid_config,
                    )

    def test_read_only_preflight_accepts_nested_lists_without_modifying_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yml"
            config_path.write_text(self.CONFIG, encoding="utf-8")
            before = config_path.read_bytes()

            cookie_line = cookie_updater.validate_cookie_update_target(config_path)

            self.assertGreater(cookie_line, 0)
            self.assertEqual(config_path.read_bytes(), before)

    def test_multiple_bilibili_tasks_leave_original_unchanged(self):
        duplicate = self.CONFIG.replace(
            "type: douyu",
            "type: bilibili",
        )
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yml"
            config_path.write_text(duplicate, encoding="utf-8")

            with self.assertRaises(cookie_updater.CookieUpdaterError):
                cookie_updater.update_cookie_in_file(
                    self.VALID_COOKIE,
                    config_path=config_path,
                )

            self.assertEqual(config_path.read_text(encoding="utf-8"), duplicate)

    def test_replace_failure_preserves_original_and_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yml"
            config_path.write_text(self.CONFIG, encoding="utf-8")
            with patch("cookie_updater.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    cookie_updater.update_cookie_in_file(
                        self.VALID_COOKIE,
                        config_path=config_path,
                    )

            self.assertEqual(config_path.read_text(encoding="utf-8"), self.CONFIG)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


class MainCleanupTest(unittest.TestCase):
    def test_expected_failure_cleans_stale_qrcode(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "qrcode.png"
            image_path.write_bytes(b"stale")
            session = Mock()
            with (
                patch("cookie_updater.validate_cookie_update_target"),
                patch("cookie_updater.create_session", return_value=session),
                patch(
                    "cookie_updater.get_qrcode",
                    side_effect=cookie_updater.CookieUpdaterError("offline"),
                ),
            ):
                result = cookie_updater.main(
                    config_path=Path(directory) / "config.yml",
                    image_path=image_path,
                )

            self.assertEqual(result, 1)
            self.assertFalse(image_path.exists())
            session.close.assert_called_once_with()

    def test_keyboard_interrupt_returns_130_and_cleans_qrcode(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "qrcode.png"
            image_path.write_bytes(b"stale")
            session = Mock()
            with (
                patch("cookie_updater.validate_cookie_update_target"),
                patch("cookie_updater.create_session", return_value=session),
                patch("cookie_updater.get_qrcode", side_effect=KeyboardInterrupt),
            ):
                result = cookie_updater.main(
                    config_path=Path(directory) / "config.yml",
                    image_path=image_path,
                )

            self.assertEqual(result, 130)
            self.assertFalse(image_path.exists())

    def test_expired_and_timeout_have_distinct_exit_codes(self):
        for error, expected_code in (
            (cookie_updater.LoginExpiredError("expired"), 2),
            (cookie_updater.LoginTimeoutError("timeout"), 3),
        ):
            with self.subTest(expected_code=expected_code):
                with tempfile.TemporaryDirectory() as directory:
                    image_path = Path(directory) / "qrcode.png"
                    session = Mock()
                    with (
                        patch("cookie_updater.validate_cookie_update_target"),
                        patch("cookie_updater.create_session", return_value=session),
                        patch("cookie_updater.get_qrcode", side_effect=error),
                    ):
                        result = cookie_updater.main(
                            config_path=Path(directory) / "config.yml",
                            image_path=image_path,
                        )

                    self.assertEqual(result, expected_code)
                    self.assertFalse(image_path.exists())


if __name__ == "__main__":
    unittest.main()
