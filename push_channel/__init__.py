from importlib import import_module

from ._push_channel import PushChannel


push_channel_dict: dict[str, PushChannel] = {}

_channel_type_to_class = {
    "serverChan_turbo": ("server_chan_turbo", "ServerChanTurbo"),
    "serverChan_3": ("server_chan_3", "ServerChan3"),
    "wecom_apps": ("wecom_apps", "WeComApps"),
    "wecom_bot": ("wecom_bot", "WeComBot"),
    "dingtalk_bot": ("dingtalk_bot", "DingtalkBot"),
    "feishu_apps": ("feishu_apps", "FeishuApps"),
    "feishu_bot": ("feishu_bot", "FeishuBot"),
    "telegram_bot": ("telegram_bot", "TelegramBot"),
    "qq_bot": ("qq_bot", "QQBot"),
    "napcat_qq": ("napcat_qq", "NapCatQQ"),
    "bark": ("bark", "Bark"),
    "gotify": ("gotify", "Gotify"),
    "webhook": ("webhook", "Webhook"),
    "email": ("email", "Email"),
    "demo": ("demo", "Demo"),
}

_class_name_to_module = {
    class_name: module_name
    for module_name, class_name in _channel_type_to_class.values()
}


def __getattr__(name):
    """Keep the previous public class imports while loading modules on demand."""
    module_name = _class_name_to_module.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    channel_class = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = channel_class
    return channel_class


def get_push_channel(config) -> PushChannel:
    channel_type = config.get("type")
    class_path = _channel_type_to_class.get(channel_type)
    if class_path is None:
        raise ValueError(f"不支持的通道类型: {channel_type}")

    module_name, class_name = class_path
    module = import_module(f"{__name__}.{module_name}")
    channel_class = getattr(module, class_name)
    return channel_class(config)
