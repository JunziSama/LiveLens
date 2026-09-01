import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from push_channel.napcat_qq import NapCatQQ


class NapCatQQTest(unittest.TestCase):
    def make_channel(self, **overrides):
        config = {
            "name": "napcat_test",
            "enable": True,
            "type": "napcat_qq",
            "ws_url": "ws://127.0.0.1:3001/",
            "token": "token",
            "group_id": "123",
        }
        config.update(overrides)
        patcher = patch("push_channel.napcat_qq.OneBotWebSocketClient")
        client_class = patcher.start()
        self.addCleanup(patcher.stop)
        client = client_class.return_value
        client.call.return_value = {
            "status": "ok",
            "retcode": 0,
            "data": {"message_id": 1},
        }
        return NapCatQQ(config), client

    def test_group_message_uses_explicit_action_and_preserves_segments(self):
        channel, client = self.make_channel()

        result = channel.push(
            title="标题",
            content="正文",
            jump_url="https://example.com",
            extend_data={"at_qq": 456},
        )

        self.assertTrue(result)
        action = client.call.call_args.kwargs["action"]
        params = client.call.call_args.kwargs["params"]
        self.assertEqual(action, "send_group_msg")
        self.assertEqual(params["group_id"], "123")
        self.assertEqual(params["message"][-1], {"type": "at", "data": {"qq": "456"}})

    def test_private_message_uses_private_action(self):
        channel, client = self.make_channel(group_id="", user_id="789")
        self.assertTrue(channel.push(title="标题", content="正文"))
        self.assertEqual(client.call.call_args.kwargs["action"], "send_private_msg")
        self.assertEqual(client.call.call_args.kwargs["params"]["user_id"], "789")

    def test_local_image_is_encoded_as_base64(self):
        channel, client = self.make_channel()
        with tempfile.TemporaryDirectory() as temp_directory:
            image_path = Path(temp_directory) / "image.jpg"
            image_path.write_bytes(b"image bytes")
            self.assertTrue(channel.push("标题", "正文", pic_url=str(image_path)))

        message = client.call.call_args.kwargs["params"]["message"]
        image_segment = next(segment for segment in message if segment["type"] == "image")
        expected = base64.b64encode(b"image bytes").decode("ascii")
        self.assertEqual(image_segment["data"]["file"], f"base64://{expected}")

    def test_exactly_one_target_is_required(self):
        with self.assertRaises(ValueError):
            self.make_channel(group_id="", user_id="")
        with self.assertRaises(ValueError):
            self.make_channel(group_id="123", user_id="789")


if __name__ == "__main__":
    unittest.main()
