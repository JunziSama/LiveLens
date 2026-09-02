from dataclasses import dataclass
from pathlib import Path

from common.logger import log


DEFAULT_TITLE = "【推送组件-启动成功】🎉"
DEFAULT_PIC_URL = "Jun.jpg"
DEFAULT_CONTENT_BEFORE = "[角落里的菌]"
DEFAULT_CONTENT_AFTER = (
    "哔哩哔哩主页：https://space.bilibili.com/591893685\n"
    "哔哩哔哩直播：http://live.bilibili.com/23075731"
)


@dataclass(frozen=True)
class StartupNotificationConfig:
    enable: bool
    target_push_name_list: tuple[str, ...]
    title: str
    content: str
    pic_url: str
    jump_url: str
    content_before: str
    content_after: str


def _as_text(value, default=""):
    if value is None:
        return default
    return str(value)


def _normalize_targets(value):
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("startup_notification.target_push_name_list 必须是列表")

    result = []
    for item in value:
        name = _as_text(item).strip()
        if name and name not in result:
            result.append(name)
    return tuple(result)


def load_startup_notification_config(common_config):
    if not isinstance(common_config, dict):
        raise ValueError("common 配置必须是对象")

    if "startup_notification" in common_config:
        raw = common_config.get("startup_notification")
        if not isinstance(raw, dict):
            raise ValueError("common.startup_notification 必须是对象")
        enabled = bool(raw.get("enable", False))
    else:
        legacy = common_config.get("push_channel", {})
        if not isinstance(legacy, dict):
            legacy = {}
        enabled = bool(legacy.get("send_test_msg_when_start", False))
        raw = {}

    return StartupNotificationConfig(
        enable=enabled,
        target_push_name_list=_normalize_targets(
            raw.get("target_push_name_list", [])
        ),
        title=_as_text(raw.get("title"), DEFAULT_TITLE),
        content=_as_text(raw.get("content"), ""),
        pic_url=_as_text(raw.get("pic_url"), DEFAULT_PIC_URL).strip(),
        jump_url=_as_text(raw.get("jump_url"), "").strip(),
        content_before=_as_text(
            raw.get("content_before"), DEFAULT_CONTENT_BEFORE
        ),
        content_after=_as_text(raw.get("content_after"), DEFAULT_CONTENT_AFTER),
    )


def resolve_startup_pic_url(pic_url, project_dir):
    if not pic_url:
        return None
    lowered = pic_url.lower()
    if lowered.startswith(("http://", "https://", "file://")):
        return pic_url

    image_path = Path(pic_url)
    if not image_path.is_absolute():
        image_path = Path(project_dir) / image_path
    image_path = image_path.resolve()
    if not image_path.is_file():
        log.warning(f"启动通知图片不存在，将发送纯文本消息：{image_path}")
        return None
    return image_path.as_uri()


def send_startup_notification(common_config, channels, project_dir):
    try:
        config = load_startup_notification_config(common_config)
    except ValueError as exc:
        log.error(f"启动通知配置无效，已跳过发送：{exc}")
        return {"sent": 0, "failed": 0}

    if not config.enable:
        return {"sent": 0, "failed": 0}

    if config.target_push_name_list:
        target_names = config.target_push_name_list
    else:
        target_names = tuple(channels.keys())

    pic_url = resolve_startup_pic_url(config.pic_url, project_dir)
    extend_data = {}
    if config.content_before:
        extend_data["content_before"] = config.content_before
    if config.content_after:
        extend_data["content_after"] = config.content_after

    sent = 0
    failed = 0
    for channel_name in target_names:
        channel = channels.get(channel_name)
        if channel is None:
            log.warning(f"启动通知目标通道不存在或未启用：{channel_name}")
            continue
        try:
            log.info(f"推送通道【{channel_name}】发送启动成功通知")
            channel.push(
                title=config.title,
                content=config.content,
                pic_url=pic_url,
                jump_url=config.jump_url or None,
                extend_data=dict(extend_data),
            )
            sent += 1
        except Exception as exc:
            failed += 1
            log.error(
                f"推送通道【{channel_name}】发送启动通知失败：{exc}",
                exc_info=True,
            )
    return {"sent": sent, "failed": failed}
