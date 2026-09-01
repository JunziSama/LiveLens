import json
import time

import push_channel  # 导入以获取群号
from common import util
from common.logger import log
from common.proxy import my_proxy
from query_task import QueryTask


class QueryDouyu(QueryTask):
    def __init__(self, config):
        super().__init__(config)
        self.room_id_list = config.get("room_id_list", [])
        self.live_start_time_dict = {}  # 记录每个房间的开播时间戳
        # 新增：开播和下播独立 @ 配置（未设置时继承 self.at_qq）
        self.at_qq_live = config.get("at_qq_live", self.at_qq)
        self.at_qq_live_end = config.get("at_qq_live_end", self.at_qq)

    def get_group_id(self):
        """从推送通道中获取群号（用于免打扰）"""
        for ch_name in self.target_push_name_list:
            ch = push_channel.push_channel_dict.get(ch_name)
            if ch and hasattr(ch, 'group_id') and ch.group_id:
                return str(ch.group_id)
        return None

    def query(self):
        if not self.enable:
            return
        try:
            current_time = time.strftime("%H:%M", time.localtime(time.time()))
            if self.begin_time <= current_time <= self.end_time:
                my_proxy.current_proxy_ip = my_proxy.get_proxy(proxy_check_url="https://www.douyu.com")
                if self.enable_living_check:
                    for room_id in self.room_id_list:
                        self.query_live_status(room_id)
        except Exception as e:
            log.error(f"【斗鱼-查询任务-{self.name}】出错：{e}", exc_info=True)

    def query_live_status(self, room_id=None):
        if room_id is None:
            return
        query_url = f'https://www.douyu.com/betard/{room_id}'
        response = util.requests_get(query_url, f"斗鱼-查询直播状态-{self.name}", use_proxy=True)
        if util.check_response_is_ok(response):
            try:
                result = json.loads(str(response.content, "utf-8"))
            except UnicodeDecodeError:
                log.error(f"【斗鱼-查询直播状态-{self.name}】【{room_id}】解析content出错")
                return

            if result is None:
                log.error(f"【斗鱼-查询直播状态-{self.name}】【{room_id}】请求返回数据为空")
                return

            room_info = result.get('room')
            # 如果 room_info 为 None，说明该房间可能已不存在或未开播，此时视为下播状态
            if room_info is None:
                log.warning(f"【斗鱼-查询直播状态-{self.name}】【{room_id}】返回 room 字段为空，视为未开播")
                # 无法获取 username，使用房间号占位
                username = f"房间{room_id}"
                show_status = 2   # 下播状态码
                avatar_url = None
                room_name = ''
                room_pic = ''
            else:
                try:
                    username = room_info.get('nickname')
                except AttributeError:
                    log.error(f"【斗鱼-查询直播状态-{self.name}】dict取值错误，room_id：{room_id}")
                    return

                avatar_url = None
                try:
                    avatar_url = room_info.get('avatar', {}).get('small') if room_info.get('avatar') else None
                except Exception:
                    log.error(f"【斗鱼-查询直播状态-{self.name}】头像获取发生错误，room_id：{room_id}")

                show_status = room_info.get('show_status', 2)  # 默认下播状态码为2
                room_name = room_info.get('room_name', '')
                room_pic = room_info.get('room_pic', '')

            jump_url = f'https://www.douyu.com/{room_id}'

            # 处理状态变化
            if self.living_status_dict.get(room_id, None) is None:
                self.living_status_dict[room_id] = show_status
                log.info(f"【斗鱼-查询直播状态-{self.name}】【{username}】初始化，状态: {show_status}")
                return

            if self.living_status_dict.get(room_id, None) != show_status:
                old_status = self.living_status_dict[room_id]
                self.living_status_dict[room_id] = show_status
                log.info(f"【斗鱼-查询直播状态-{self.name}】【{username}】状态变化: {old_status} -> {show_status}")

                if show_status == 1:
                    # 开播：记录开播时间戳
                    self.live_start_time_dict[room_id] = time.time()
                    log.info(f"【斗鱼-查询直播状态-{self.name}】【{username}】开播了，准备推送：{room_name}")
                    self.push_for_douyu_live(username=username, room_title=room_name, jump_url=jump_url,
                                             room_cover_url=room_pic, avatar_url=avatar_url)
                elif show_status != 1:
                    # 下播：发送下播提醒（斗鱼下播状态通常为2，此处统一处理非1的状态）
                    log.info(f"【斗鱼-查询直播状态-{self.name}】【{username}】下播了，准备推送，状态码: {show_status}")
                    self.push_for_douyu_live_end(username=username, room_id=room_id, room_title=room_name,
                                                 jump_url=jump_url, avatar_url=avatar_url)
        else:
            log.error(f"【斗鱼-查询直播状态-{self.name}】【{room_id}】请求失败")

    # ---------- 封面获取多重回退机制 ----------
    def _get_cover_from_mixlist(self, room_id):
        """方法1：使用网页列表API获取封面（最稳定）"""
        try:
            api_url = "https://www.douyu.com/gapi/rkc/directory/mixList/0_0/1"
            resp = util.requests_get(api_url, f"斗鱼-列表API获取封面-{self.name}", use_proxy=True)
            if resp and resp.status_code == 200:
                data = resp.json()
                if data and data.get('data', {}).get('rl'):
                    for room_info in data['data']['rl']:
                        if str(room_info.get('rid')) == room_id:
                            cover = room_info.get('rs1')
                            if cover:
                                log.info(f"【斗鱼-列表API封面获取成功-{self.name}】: {cover}")
                                return cover
        except Exception as e:
            log.warning(f"【斗鱼-列表API封面获取失败-{self.name}】: {e}")
        return None

    def _get_cover_from_betard(self, room_id):
        """方法2：修正原betard接口（需Referer）"""
        try:
            api_url = f"https://www.douyu.com/betard/{room_id}"
            headers = {"Referer": "https://www.douyu.com/"}
            resp = util.requests_get(api_url, f"斗鱼-原接口获取封面-{self.name}", headers=headers, use_proxy=True)
            if resp and resp.status_code == 200:
                data = resp.json()
                cover = data.get('room', {}).get('room_pic')
                if cover:
                    log.info(f"【斗鱼-原接口封面获取成功-{self.name}】: {cover}")
                    return cover
        except Exception as e:
            log.warning(f"【斗鱼-原接口封面获取失败-{self.name}】: {e}")
        return None

    def _get_cover_from_openapi(self, room_id):
        """方法3：经典开放API"""
        try:
            api_url = f"http://open.douyucdn.cn/api/RoomApi/room/{room_id}"
            resp = util.requests_get(api_url, f"斗鱼-经典API获取封面-{self.name}", use_proxy=True)
            if resp and resp.status_code == 200:
                data = resp.json()
                cover = data.get('data', {}).get('room_pic')
                if cover:
                    log.info(f"【斗鱼-经典API封面获取成功-{self.name}】: {cover}")
                    return cover
        except Exception as e:
            log.warning(f"【斗鱼-经典API封面获取失败-{self.name}】: {e}")
        return None

    def _get_room_cover(self, room_id):
        """综合方法：依次尝试多个接口，返回第一个有效的封面URL"""
        if not room_id:
            return None
        # 按优先级尝试
        cover = self._get_cover_from_mixlist(room_id)
        if cover:
            return cover
        cover = self._get_cover_from_betard(room_id)
        if cover:
            return cover
        cover = self._get_cover_from_openapi(room_id)
        if cover:
            return cover
        log.warning(f"【斗鱼-所有封面获取方式均失败-{self.name}】房间号: {room_id}")
        return None

    # ---------- 推送方法 ----------
    def push_for_douyu_live(self, username=None, room_title=None, jump_url=None, room_cover_url=None, avatar_url=None):
        """
        斗鱼开播提醒推送（与B站排版一致，支持免打扰）
        """
        title = "【开播提醒-斗鱼】"
        content_before = f"[{username}]开播啦~"
        content_after = f"\n[{room_title}]\n\n直播间地址：{jump_url}"

        # 获取房间ID（从jump_url中提取）
        room_id = None
        if jump_url:
            room_id = jump_url.rstrip('/').split('/')[-1]
            if not room_id.isdigit():
                room_id = None

        # 尝试获取封面（使用多重回退机制）
        effective_cover_url = self._get_room_cover(room_id) if room_id else None
        if not effective_cover_url:
            log.warning(f"【斗鱼-未获取到有效封面-{self.name}】，本次推送将不包含图片")

        group_id = self.get_group_id()
        at_qq_value = self.at_qq_live
        mute_text = ""
        if group_id and at_qq_value:
            is_mute, mute_text = self.check_mute("live", group_id, at_qq_value)
            if is_mute:
                at_qq_value = None

        extend_data = {
            'avatar_url': avatar_url,
            'content_before': content_before,
            'content_after': content_after,
            'at_qq': at_qq_value
        }
        if mute_text:
            extend_data['mute_text'] = mute_text

        # 发送消息（如果effective_cover_url为None则不传图片）
        super().push(title, "", None, effective_cover_url, extend_data=extend_data)

    def push_for_douyu_live_end(self, username=None, room_id=None, room_title=None, jump_url=None, avatar_url=None):
        """
        斗鱼下播提醒推送（与B站排版一致，支持免打扰）
        """
        if username is None or room_id is None:
            log.error(f"【斗鱼-下播提醒推送-{self.name}】缺少参数")
            return

        start_time = self.live_start_time_dict.get(room_id)
        if start_time is None:
            duration_text = "未知"
            log.warning(f"【斗鱼-下播提醒推送-{self.name}】【{username}】未找到开播时间戳，可能是程序启动前已开播")
        else:
            end_time = time.time()
            duration_seconds = int(end_time - start_time)
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            start_str = time.strftime("%H:%M", time.localtime(start_time))
            end_str = time.strftime("%H:%M", time.localtime(end_time))
            # 统一格式：x小时y分钟
            if hours == 0:
                duration_str = f"0小时{minutes}分钟"
            elif minutes == 0:
                duration_str = f"{hours}小时0分钟"
            else:
                duration_str = f"{hours}小时{minutes}分钟"
            duration_text = f"{start_str}~{end_str}({duration_str})"

        content = f"[{username}]下播啦！\n直播时长：{duration_text}"

        group_id = self.get_group_id()
        at_qq_value = self.at_qq_live_end
        mute_text = ""
        if group_id and at_qq_value:
            is_mute, mute_text = self.check_mute("live_end", group_id, at_qq_value)
            if is_mute:
                at_qq_value = None

        extend_data = {
            'avatar_url': avatar_url,
            'at_qq': at_qq_value
        }
        if mute_text:
            extend_data['mute_text'] = mute_text

        super().push("【下播提醒-斗鱼】", content, None, None, extend_data=extend_data)