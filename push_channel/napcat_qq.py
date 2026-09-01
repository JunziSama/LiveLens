import json

from common import util
from common.logger import log
from . import PushChannel


class NapCatQQ(PushChannel):
    """
    Author: https://github.com/YingChengxi
    See: https://github.com/nfe-w/aio-dynamic-push/issues/50
    """

    def __init__(self, config):
        super().__init__(config)
        self.api_url = str(config.get("api_url", ""))
        self.token = str(config.get("token", ""))
        _user_id = config.get("user_id", None)
        self.user_id = str(_user_id) if _user_id else None
        _group_id = config.get("group_id", None)
        self.group_id = str(_group_id) if _group_id else None
        _at_qq = config.get("at_qq", None)
        self.at_qq = str(_at_qq) if _at_qq else None
        if not self.api_url or (not self.user_id and not self.group_id):
            log.error(f"【推送_{self.name}】配置不完整，推送功能将无法正常使用")
        if self.user_id and self.group_id:
            log.error(f"【推送_{self.name}】配置错误，不能同时设置 user_id 和 group_id")

    def push(self, title, content, jump_url=None, pic_url=None, extend_data=None):
        message = []

        # 确定使用的 at_qq（优先使用 extend_data 中的，否则使用自身配置）
        if extend_data and extend_data.get('at_qq') is not None:
            at_qq = extend_data['at_qq']
            # 确保是字符串（YAML 可能读成数字）
            if not isinstance(at_qq, str):
                at_qq = str(at_qq)
        else:
            at_qq = self.at_qq

        # 免打扰文本（如果存在）
        mute_text = extend_data.get('mute_text') if extend_data else None

        # 1. 标题（后跟两个换行）
        if title:
            message.append({
                "type": "text",
                "data": {"text": f"{title}\n\n"}
            })

        # 2. 图片前的内容
        if extend_data and extend_data.get('content_before'):
            message.append({
                "type": "text",
                "data": {"text": extend_data['content_before']}
            })
        elif content:
            pass  # 下面会处理

        # 3. 图片
        if pic_url:
            message.append({
                "type": "image",
                "data": {"file": pic_url}
            })
            # 图片后不加换行（空字符串）
            message.append({
                "type": "text",
                "data": {"text": ""}
            })

        # 4. 图片后的内容
        if extend_data and extend_data.get('content_after'):
            message.append({
                "type": "text",
                "data": {"text": extend_data['content_after']}
            })
        elif content:
            message.append({
                "type": "text",
                "data": {"text": content}
            })

        # 5. 原文链接
        if jump_url:
            message.append({
                "type": "text",
                "data": {"text": f"\n\n原文: {jump_url}"}
            })

        # 6. 处理 @ 或免打扰提示
        if mute_text:
            # 免打扰模式：不发送 @，改为发送提示文本
            message.append({
                "type": "text",
                "data": {"text": f"\n{mute_text}"}
            })
        elif at_qq:
            # 正常 @
            message.append({
                "type": "text",
                "data": {"text": "\n"}
            })
            message.append({
                "type": "at",
                "data": {"qq": at_qq}
            })

        # 构建发送 payload
        payload = {
            "user_id": self.user_id,
            "group_id": self.group_id,
            "message": message
        }
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        api_endpoint = f"{self.api_url.rstrip('/')}/send_msg"

        try:
            response = util.requests_post(
                api_endpoint,
                self.name,
                headers=headers,
                data=json.dumps(payload)
            )

            # 增强空值判断
            if response is None:
                log.error(f"【推送_{self.name}】请求失败，未收到响应（可能是网络超时或连接错误）")
                return False

            if util.check_response_is_ok(response):
                resp_data = response.json()
                if resp_data.get("status") == "ok" and resp_data.get("retcode") == 0:
                    log.info(f"【推送_{self.name}】消息发送成功")
                    return True
                else:
                    error_msg = resp_data.get("message", "未知错误")
                    log.error(f"【推送_{self.name}】API返回错误: {error_msg}")
            else:
                log.error(f"【推送_{self.name}】请求失败，状态码: {response.status_code}")

        except Exception as e:
            log.error(f"【推送_{self.name}】发送消息时出现异常: {str(e)}")
            return False

        return False