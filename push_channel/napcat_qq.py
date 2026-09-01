import base64
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from common.logger import log
from common.onebot_ws import OneBotWebSocketClient, OneBotWebSocketError
from . import PushChannel


class NapCatQQ(PushChannel):
    """Send OneBot 11 messages through a NapCat forward WebSocket server."""

    def __init__(self, config):
        super().__init__(config)
        self.ws_url = self._optional_string(config.get("ws_url")) or ""
        self.token = self._optional_string(config.get("token")) or ""
        self.user_id = self._optional_string(config.get("user_id"))
        self.group_id = self._optional_string(config.get("group_id"))
        self.at_qq = self._optional_string(config.get("at_qq"))
        self.connect_timeout = self._positive_float(
            config.get("connect_timeout", 5), "connect_timeout"
        )
        self.response_timeout = self._positive_float(
            config.get("response_timeout", 30), "response_timeout"
        )

        parsed_url = urlparse(self.ws_url)
        if parsed_url.scheme not in ("ws", "wss") or not parsed_url.netloc:
            raise ValueError(
                f"推送通道 {self.name} 的 ws_url 必须是有效的 ws:// 或 wss:// 地址"
            )
        if bool(self.user_id) == bool(self.group_id):
            raise ValueError(
                f"推送通道 {self.name} 必须且只能配置 user_id、group_id 其中一个"
            )

        self.client = OneBotWebSocketClient(
            url=self.ws_url,
            token=self.token,
            connect_timeout=self.connect_timeout,
            name=self.name,
        )
        self.client.start()

    def push(self, title, content, jump_url=None, pic_url=None, extend_data=None):
        message = self._build_message(
            title=title,
            content=content,
            jump_url=jump_url,
            pic_url=pic_url,
            extend_data=extend_data or {},
        )
        if not message:
            log.warning(f"【推送_{self.name}】消息内容为空，已跳过发送")
            return False

        if self.group_id:
            action = "send_group_msg"
            params = {"group_id": self.group_id, "message": message}
        else:
            action = "send_private_msg"
            params = {"user_id": self.user_id, "message": message}

        try:
            response = self.client.call(
                action=action,
                params=params,
                timeout=self.response_timeout,
            )
        except OneBotWebSocketError as exc:
            log.error(f"【推送_{self.name}】消息发送失败: {exc}")
            return False
        except Exception as exc:
            log.error(f"【推送_{self.name}】消息发送异常: {exc}")
            return False

        if response.get("status") == "ok" and response.get("retcode") == 0:
            message_id = (response.get("data") or {}).get("message_id")
            suffix = f"，message_id={message_id}" if message_id is not None else ""
            log.info(f"【推送_{self.name}】消息发送成功{suffix}")
            return True

        error_message = response.get("message") or response.get("wording") or "未知错误"
        log.error(
            f"【推送_{self.name}】OneBot 返回错误: retcode="
            f"{response.get('retcode')}，{error_message}"
        )
        return False

    def close(self):
        self.client.close()

    def _build_message(self, title, content, jump_url, pic_url, extend_data):
        message = []
        at_qq = self._optional_string(extend_data.get("at_qq")) or self.at_qq
        mute_text = extend_data.get("mute_text")

        if title:
            message.append({"type": "text", "data": {"text": f"{title}\n\n"}})

        if extend_data.get("content_before"):
            message.append(
                {
                    "type": "text",
                    "data": {"text": str(extend_data["content_before"])},
                }
            )

        image_source = self._normalize_image_source(pic_url) if pic_url else None
        if image_source:
            message.append({"type": "image", "data": {"file": image_source}})
            message.append({"type": "text", "data": {"text": ""}})

        if extend_data.get("content_after"):
            message.append(
                {
                    "type": "text",
                    "data": {"text": str(extend_data["content_after"])},
                }
            )
        elif content:
            message.append({"type": "text", "data": {"text": str(content)}})

        if jump_url:
            message.append(
                {"type": "text", "data": {"text": f"\n\n原文: {jump_url}"}}
            )

        if mute_text:
            message.append(
                {"type": "text", "data": {"text": f"\n{mute_text}"}}
            )
        elif at_qq:
            message.append({"type": "text", "data": {"text": "\n"}})
            message.append({"type": "at", "data": {"qq": at_qq}})

        return message

    def _normalize_image_source(self, source):
        source = str(source).strip()
        if Path(source).is_absolute():
            return self._encode_local_image(Path(source))

        parsed = urlparse(source)
        if parsed.scheme in ("http", "https", "base64", "data"):
            return source

        if parsed.scheme == "file":
            local_path = Path(url2pathname(unquote(parsed.path)))
        elif not parsed.scheme:
            local_path = Path(source)
        else:
            log.warning(f"【推送_{self.name}】不支持的图片地址，已仅发送文本: {source}")
            return None

        return self._encode_local_image(local_path)

    def _encode_local_image(self, local_path):
        try:
            encoded = base64.b64encode(local_path.read_bytes()).decode("ascii")
            return f"base64://{encoded}"
        except OSError as exc:
            log.warning(f"【推送_{self.name}】读取本地图片失败，已仅发送文本: {exc}")
            return None

    @staticmethod
    def _optional_string(value):
        if value is None:
            return None
        result = str(value).strip()
        return result or None

    @staticmethod
    def _positive_float(value, field_name):
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} 必须是数字") from exc
        if result <= 0:
            raise ValueError(f"{field_name} 必须大于 0")
        return result
