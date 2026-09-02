import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from common import startup_notification


class StartupNotificationConfigTest(unittest.TestCase):
    def test_new_disabled_config_overrides_enabled_legacy_switch(self):
        config = startup_notification.load_startup_notification_config(
            {
                "push_channel": {"send_test_msg_when_start": True},
                "startup_notification": {"enable": False},
            }
        )

        self.assertFalse(config.enable)

    def test_legacy_switch_uses_original_message(self):
        config = startup_notification.load_startup_notification_config(
            {"push_channel": {"send_test_msg_when_start": True}}
        )

        self.assertTrue(config.enable)
        self.assertEqual(config.title, startup_notification.DEFAULT_TITLE)
        self.assertEqual(
            config.content_after,
            startup_notification.DEFAULT_CONTENT_AFTER,
        )

    def test_targets_are_deduplicated_in_order(self):
        config = startup_notification.load_startup_notification_config(
            {
                "startup_notification": {
                    "enable": True,
                    "target_push_name_list": ["one", "two", "one", ""],
                }
            }
        )

        self.assertEqual(config.target_push_name_list, ("one", "two"))


class StartupNotificationImageTest(unittest.TestCase):
    def test_relative_image_is_converted_to_file_uri(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "image.jpg"
            image_path.write_bytes(b"image")

            result = startup_notification.resolve_startup_pic_url(
                "image.jpg", directory
            )

        self.assertEqual(result, image_path.resolve().as_uri())

    def test_remote_and_file_urls_are_preserved(self):
        for url in (
            "https://example.invalid/image.jpg",
            "http://example.invalid/image.jpg",
            "file:///C:/images/image.jpg",
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    startup_notification.resolve_startup_pic_url(url, "."),
                    url,
                )

    def test_missing_image_falls_back_to_text_only(self):
        with patch.object(startup_notification.log, "warning") as warning:
            result = startup_notification.resolve_startup_pic_url(
                "missing.jpg", "."
            )

        self.assertIsNone(result)
        warning.assert_called_once()


class StartupNotificationSendTest(unittest.TestCase):
    def config(self, **overrides):
        values = {
            "enable": True,
            "target_push_name_list": [],
            "title": "title",
            "content": "content",
            "pic_url": "https://example.invalid/image.jpg",
            "jump_url": "https://example.invalid/jump",
            "content_before": "before",
            "content_after": "after",
        }
        values.update(overrides)
        return {"startup_notification": values}

    def test_empty_targets_send_to_all_channels_with_configured_fields(self):
        first = Mock()
        second = Mock()

        result = startup_notification.send_startup_notification(
            self.config(), {"first": first, "second": second}, "."
        )

        self.assertEqual(result, {"sent": 2, "failed": 0})
        expected = {
            "title": "title",
            "content": "content",
            "pic_url": "https://example.invalid/image.jpg",
            "jump_url": "https://example.invalid/jump",
            "extend_data": {
                "content_before": "before",
                "content_after": "after",
            },
        }
        first.push.assert_called_once_with(**expected)
        second.push.assert_called_once_with(**expected)

    def test_selected_and_unknown_targets_are_handled_independently(self):
        first = Mock()
        second = Mock()
        config = self.config(
            target_push_name_list=["second", "missing", "second"]
        )

        with patch.object(startup_notification.log, "warning") as warning:
            result = startup_notification.send_startup_notification(
                config, {"first": first, "second": second}, "."
            )

        self.assertEqual(result, {"sent": 1, "failed": 0})
        first.push.assert_not_called()
        second.push.assert_called_once()
        warning.assert_called_once()

    def test_channel_failure_does_not_block_other_channels(self):
        failed = Mock()
        failed.push.side_effect = RuntimeError("offline")
        healthy = Mock()

        with patch.object(startup_notification.log, "error") as error:
            result = startup_notification.send_startup_notification(
                self.config(), {"failed": failed, "healthy": healthy}, "."
            )

        self.assertEqual(result, {"sent": 1, "failed": 1})
        healthy.push.assert_called_once()
        error.assert_called_once()

    def test_disabled_notification_does_not_send(self):
        channel = Mock()

        result = startup_notification.send_startup_notification(
            self.config(enable=False), {"channel": channel}, "."
        )

        self.assertEqual(result, {"sent": 0, "failed": 0})
        channel.push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
