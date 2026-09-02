import time
import requests  # 添加这一行
from collections import deque

import push_channel
from common import util
from common.cache import set_cached_value, get_cached_value
from common.logger import log
from common.proxy import my_proxy
from query_task import QueryTask
from common.wbi import get_wbi_keys, encrypt_wbi


class QueryBilibili(QueryTask):
    def __init__(self, config):
        super().__init__(config)
        self.uid_list = config.get("uid_list", [])
        self.skip_forward = config.get("skip_forward", True)
        self.cookie = config.get("cookie", "")
        self.payload = config.get("payload", "")
        self.buvid3 = None
        self.live_start_time_dict = {}
        # 三个动作独立 @ 配置
        self.at_qq_dynamic = config.get("at_qq_dynamic", self.at_qq)
        self.at_qq_live = config.get("at_qq_live", self.at_qq)
        self.at_qq_live_end = config.get("at_qq_live_end", self.at_qq)

        # 预热标志
        self._warmed = False
        # 使用 Session 保持连接
        self.session = None

    def _get_session(self):
        """获取或创建带完整头部的 Session"""
        if self.session is None:
            self.session = requests.Session()
            # 设置通用请求头
            self.session.headers.update({
                "accept": "application/json, text/plain, */*",
                "accept-encoding": "gzip, deflate",
                "accept-language": "zh-CN,zh;q=0.9",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Microsoft Edge";v="120"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"'
            })
        return self.session

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
            self.init_buvid3()

            # 预热：首次运行时访问B站首页，获取完整环境（降低风控）
            if not self._warmed:
                try:
                    log.info("执行B站预热，访问首页...")
                    warm_headers = self.get_headers(self.uid_list[0] if self.uid_list else '1')
                    warm_response = util.requests_get(
                        'https://www.bilibili.com/',
                        "B站预热",
                        headers=warm_headers,
                        use_proxy=True,
                        session=self._get_session(),
                        retryable=True,
                    )
                    if warm_response and warm_response.status_code == 200:
                        log.info("B站预热成功")
                    else:
                        log.warning(f"B站预热返回状态码: {warm_response.status_code if warm_response else 'No Response'}")
                except Exception as e:
                    log.warning(f"B站预热失败: {e}")
                self._warmed = True

            current_time = time.strftime("%H:%M", time.localtime(time.time()))
            if self.begin_time <= current_time <= self.end_time:
                my_proxy.current_proxy_ip = my_proxy.get_proxy(proxy_check_url="http://api.bilibili.com/x/space/acc/info")
                if self.enable_dynamic_check:
                    for uid in self.uid_list:
                        self.query_dynamic_v2(uid)
                        time.sleep(1)
                if self.enable_living_check:
                    self.query_live_status_batch(self.uid_list)
        except Exception as e:
            log.error(f"【哔哩哔哩-查询任务-{self.name}】出错：{e}", exc_info=True)

    def init_buvid3(self, get_from_cache=True):
        buvid3 = None
        if get_from_cache:
            buvid3 = get_cached_value("buvid3")
        if buvid3 is None:
            buvid3 = self.get_new_buvid3()
            if buvid3:
                set_cached_value("buvid3", buvid3)
        self.buvid3 = buvid3

    def get_new_buvid3(self):
        buvid3 = self.generate_buvid3()
        if not buvid3:
            log.error(f"【哔哩哔哩-查询动态状态-{self.name}】未能生成有效 buvid3")
            return None
        if not self.payload:
            log.info(
                f"【哔哩哔哩-查询动态状态-{self.name}】未配置 payload，"
                "跳过 buvid3 激活"
            )
            return buvid3

        url = "https://api.bilibili.com/x/internal/gaia-gateway/ExClimbWuzhi"
        headers = {
            'content-type': 'application/json;charset=UTF-8',
            'cookie': f'buvid3={buvid3};'
        }
        response = util.requests_post(
            url,
            f"哔哩哔哩-查询动态状态-激活buvid3-{self.name}",
            headers=headers,
            json={"payload": self.payload},
            use_proxy=True,
            session=self._get_session(),
            retryable=False,
        )
        data = self._response_json(response, "激活 buvid3")
        if data is not None:
            code = data.get("code", -1)
            message = data.get("message", "")
            if code == 0:
                log.info(f"【哔哩哔哩-查询动态状态-激活buvid3-{self.name}】激活成功")
            else:
                log.error(f"【哔哩哔哩-查询动态状态-激活buvid3-{self.name}】激活失败, code：{code}, message: {message}")
        return buvid3

    def generate_buvid3(self):
        url = "https://api.bilibili.com/x/frontend/finger/spi"
        headers = {}
        response = util.requests_get(
            url,
            f"哔哩哔哩-查询动态状态-spi-{self.name}",
            headers=headers,
            use_proxy=True,
            session=self._get_session(),
            retryable=True,
        )
        result = self._response_json(response, "请求 buvid3")
        if result is not None:
            data = result.get("data")
            if not isinstance(data, dict):
                return None
            buvid3 = data.get("b_3")
            return buvid3
        return None

    def query_dynamic_v2(self, uid=None, is_retry_by_buvid3=False):
        if uid is None:
            return
        uid = str(uid)

        # 构建基础参数字典
        base_params = {
            "host_mid": uid,
            "offset": "",
            "my_ts": int(time.time()),
            "features": "itemOpusStyle"
        }

        # 尝试添加 WBI 签名
        try:
            img_key, sub_key = get_wbi_keys()
            signed_params = encrypt_wbi(base_params, img_key, sub_key)
            query_url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?" + "&".join([f"{k}={v}" for k, v in signed_params.items()])
        except Exception as e:
            log.error(f"WBI签名生成失败，降级使用无签名请求: {e}")
            query_url = (f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
                         f"?host_mid={uid}&offset=&my_ts={int(time.time())}&features=itemOpusStyle")

        # 构建请求头
        headers = self.get_headers(uid)
        # 合并 Cookie：优先使用完整的 cookie（SESSDATA等），如果存在则覆盖 buvid3 部分
        cookie_parts = []
        if self.cookie:
            cookie_parts.append(self.cookie.rstrip(';'))
        if self.buvid3 and 'buvid3' not in self.cookie:
            cookie_parts.append(f"buvid3={self.buvid3}")
        if cookie_parts:
            headers["cookie"] = "; ".join(cookie_parts)
        else:
            headers["cookie"] = "l=v;"

        # 使用 Session 发送请求（增强稳定性）
        session = self._get_session()
        # 临时更新 headers 中的 cookie
        session.headers.update({"cookie": headers["cookie"]})
        response = util.requests_get(
            query_url,
            f"哔哩哔哩-查询动态状态-{self.name}",
            use_proxy=True,
            session=session,
            retryable=True,
        )
        result = self._response_json(response, "查询动态状态")
        if result is None:
            return

        if result["code"] != 0:
            log.error(f"【哔哩哔哩-查询动态状态-{self.name}】请求返回数据code错误：{result['code']}")
            if result["code"] == -352:
                if is_retry_by_buvid3 is True:
                    log.error(f"【哔哩哔哩-查询动态状态-{self.name}】已经重试获取了【{uid}】，但依然失败")
                    return
                self.init_buvid3(get_from_cache=False)
                log.info(f"【哔哩哔哩-查询动态状态-{self.name}】重新获取到了buvid3：{self.buvid3}")
                log.info(f"【哔哩哔哩-查询动态状态-{self.name}】重试获取【{uid}】的动态")
                self.query_dynamic_v2(uid, is_retry_by_buvid3=True)
                return
            else:
                return

        data = result["data"]
        if "items" not in data or data["items"] is None or len(data["items"]) == 0:
            log.warning(f"【哔哩哔哩-查询动态状态-{self.name}】【{uid}】返回动态列表为空")
            return

        items = data["items"]
        items = [item for item in items if
                 (item["modules"].get("module_tag", None) is None or item["modules"].get("module_tag").get("text", None) != "置顶")]
        if len(items) == 0:
            log.warning(f"【哔哩哔哩-查询动态状态-{self.name}】【{uid}】跳过置顶后动态列表为空")
            return

        if self.dynamic_dict.get(uid, None) is None:
            self.dynamic_dict[uid] = deque(maxlen=self.len_of_deque)
            for idx in range(min(self.len_of_deque, len(items))):
                self.dynamic_dict[uid].appendleft(items[idx]["id_str"])
            log.info(f"【哔哩哔哩-查询动态状态-{self.name}】【{uid}】动态初始化，填充了 {len(self.dynamic_dict[uid])} 条记录")
            return

        item = items[0]
        dynamic_id = item["id_str"]
        try:
            uname = item["modules"]["module_author"]["name"]
        except KeyError:
            log.error(f"【哔哩哔哩-查询动态状态-{self.name}】【{uid}】获取不到uname")
            return

        avatar_url = None
        try:
            avatar_url = item["modules"]["module_author"]["face"]
        except Exception:
            log.error(f"【哔哩哔哩-查询动态状态-{self.name}】头像获取发生错误，uid：{uid}")

        if dynamic_id not in self.dynamic_dict[uid]:
            previous_dynamic_id = self.dynamic_dict[uid].pop()
            self.dynamic_dict[uid].append(previous_dynamic_id)
            log.info(f"【哔哩哔哩-查询动态状态-{self.name}】【{uname}】上一条动态id[{previous_dynamic_id}]，本条动态id[{dynamic_id}]")
            self.dynamic_dict[uid].append(dynamic_id)

            dynamic_type = item["type"]
            allow_type_list = ["DYNAMIC_TYPE_DRAW", "DYNAMIC_TYPE_WORD", "DYNAMIC_TYPE_AV", "DYNAMIC_TYPE_ARTICLE", "DYNAMIC_TYPE_COMMON_SQUARE"]
            if self.skip_forward is False:
                allow_type_list.append("DYNAMIC_TYPE_FORWARD")
            if dynamic_type not in allow_type_list:
                log.info(f"【哔哩哔哩-查询动态状态-{self.name}】【{uname}】动态有更新，但不在需要推送的动态类型列表中，dynamic_type->{dynamic_type}")
                return

            timestamp = int(item["modules"]["module_author"]["pub_ts"])
            dynamic_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
            module_dynamic = item["modules"]["module_dynamic"]

            raw_content = None
            pic_url = None
            title_msg = "发动态了"
            if dynamic_type == "DYNAMIC_TYPE_FORWARD":
                raw_content = module_dynamic["desc"]["text"]
                title_msg = "转发了动态"
            elif dynamic_type == "DYNAMIC_TYPE_DRAW":
                if module_dynamic["major"]["type"] == "MAJOR_TYPE_OPUS":
                    raw_content = module_dynamic["major"]["opus"]["summary"]["text"]
                    try:
                        title = module_dynamic["major"]["opus"]["title"]
                        raw_content = f"「{title}」{raw_content}" if title else raw_content
                    except Exception:
                        pass
                    try:
                        pic_url = module_dynamic["major"]["opus"]["pics"][0]["url"]
                    except Exception:
                        pass
                else:
                    raw_content = module_dynamic["desc"]["text"]
                    try:
                        pic_url = module_dynamic["major"]["draw"]["items"][0]["src"]
                    except Exception:
                        pass
            elif dynamic_type == "DYNAMIC_TYPE_WORD":
                raw_content = module_dynamic["desc"]["text"]
            elif dynamic_type == "DYNAMIC_TYPE_AV":
                raw_content = module_dynamic["major"]["archive"]["title"]
                pic_url = module_dynamic["major"]["archive"]["cover"]
                title_msg = "投稿了"
            elif dynamic_type == "DYNAMIC_TYPE_ARTICLE":
                raw_content = module_dynamic["major"]["opus"]["title"]
                try:
                    pic_url = module_dynamic["major"]["opus"]["pics"][0]["url"]
                except Exception:
                    pass
            elif dynamic_type == "DYNAMIC_TYPE_COMMON_SQUARE":
                raw_content = module_dynamic["desc"]["text"]

            if raw_content is None:
                raw_content = ""
            display_content = raw_content[:100] + (raw_content[100:] and '...') if raw_content else ""
            log.info(f"【哔哩哔哩-查询动态状态-{self.name}】【{uname}】动态有更新，准备推送：{display_content[:30]}")
            self.push_for_bili_dynamic(uname, dynamic_id, display_content, pic_url, dynamic_type, dynamic_time, title_msg, dynamic_raw_data=item, avatar_url=avatar_url, raw_content=raw_content)

    @DeprecationWarning
    def query_dynamic(self, uid=None):
        pass

    def query_live_status_batch(self, uid_list=None):
        if uid_list is None:
            uid_list = []
        if len(uid_list) == 0:
            return
        query_url = "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"
        headers = self.get_headers(uid_list[0])
        # 合并 Cookie
        cookie_parts = []
        if self.cookie:
            cookie_parts.append(self.cookie.rstrip(';'))
        if self.buvid3 and 'buvid3' not in self.cookie:
            cookie_parts.append(f"buvid3={self.buvid3}")
        if cookie_parts:
            headers["cookie"] = "; ".join(cookie_parts)
        else:
            headers["cookie"] = "l=v;"

        response = util.requests_post(
            query_url,
            "哔哩哔哩-查询直播状态",
            headers=headers,
            json={"uids": list(map(int, uid_list))},
            use_proxy=True,
            session=self._get_session(),
            retryable=True,
        )
        result = self._response_json(response, "查询直播状态")
        if result is not None:
            if result["code"] != 0:
                log.error(f"【哔哩哔哩-查询直播状态-{self.name}】请求返回数据code错误：{result['code']}")
            else:
                live_status_list = result["data"]
                if len(live_status_list) == 0:
                    return
                for uid, item_info in live_status_list.items():
                    try:
                        uname = item_info["uname"]
                        live_status = item_info["live_status"]
                    except (KeyError, TypeError):
                        log.error(f"【哔哩哔哩-查询直播状态-{self.name}】【{uid}】获取不到live_status")
                        continue

                    avatar_url = None
                    try:
                        avatar_url = item_info["face"]
                    except Exception:
                        log.error(f"【哔哩哔哩-查询动态状态-{self.name}】头像获取发生错误，uid：{uid}")

                    if self.living_status_dict.get(uid, None) is None:
                        self.living_status_dict[uid] = live_status
                        log.info(f"【哔哩哔哩-查询直播状态-{self.name}】【{uname}】初始化")
                        continue

                    if self.living_status_dict.get(uid, None) != live_status:
                        self.living_status_dict[uid] = live_status

                        room_id = item_info["room_id"]
                        room_title = item_info["title"]
                        room_cover_url = item_info["cover_from_user"]

                        if live_status == 1:
                            self.live_start_time_dict[uid] = time.time()
                            log.info(f"【哔哩哔哩-查询直播状态-{self.name}】【{uname}】开播了，准备推送：{room_title}")
                            self.push_for_bili_live(uname, room_id, room_title, room_cover_url, avatar_url=avatar_url)
                        elif live_status == 0:
                            log.info(f"【哔哩哔哩-查询直播状态-{self.name}】【{uname}】下播了，准备推送")
                            self.push_for_bili_live_end(uname, uid, room_title, avatar_url=avatar_url)
        else:
            log.error(f"【哔哩哔哩-查询直播状态-{self.name}】请求失败")

    def _response_json(self, response, operation):
        if response is None:
            return None
        if response.status_code == 412:
            log.warning(
                f"【哔哩哔哩-{operation}-{self.name}】触发 412 风控，"
                "已跳过本轮请求"
            )
            return None
        if response.status_code != 200:
            log.error(
                f"【哔哩哔哩-{operation}-{self.name}】HTTP 状态码: "
                f"{response.status_code}"
            )
            return None
        content_type = response.headers.get("Content-Type", "").lower()
        if "json" not in content_type:
            log.error(
                f"【哔哩哔哩-{operation}-{self.name}】返回内容不是 JSON: "
                f"{content_type or '未知类型'}"
            )
            return None
        try:
            result = response.json()
        except (requests.exceptions.JSONDecodeError, ValueError) as exc:
            log.error(f"【哔哩哔哩-{operation}-{self.name}】JSON 解析失败: {exc}")
            return None
        if not isinstance(result, dict):
            log.error(f"【哔哩哔哩-{operation}-{self.name}】JSON 顶层不是对象")
            return None
        return result

    @staticmethod
    def get_headers(uid):
        return {
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "origin": "https://space.bilibili.com",
            "pragma": "no-cache",
            "referer": f"https://space.bilibili.com/{uid}/dynamic",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Microsoft Edge";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"'
        }

    def push_for_bili_dynamic(self, uname=None, dynamic_id=None, display_content=None, pic_url=None,
                              dynamic_type=None, dynamic_time=None, title_msg='发动态了', dynamic_raw_data=None, avatar_url=None, raw_content=None):
        """
        哔哩哔哩动态提醒推送（自定义排版，支持免打扰）
        """
        if uname is None or dynamic_id is None:
            log.error(f"【哔哩哔哩-动态提醒推送-{self.name}】缺少参数")
            return

        title = "【动态提醒-哔哩哔哩】"
        content_before = f"[{uname}]{title_msg}~"
        body = (raw_content if raw_content else (display_content or "")).rstrip('\n')
        content_after = f"\n{body}\n\n{dynamic_time}\n动态地址：https://www.bilibili.com/opus/{dynamic_id}"

        group_id = self.get_group_id()
        at_qq_value = self.at_qq_dynamic
        mute_text = ""
        if group_id and at_qq_value:
            is_mute, mute_text = self.check_mute("dynamic", group_id, at_qq_value)
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

        super().push(title, "", None, pic_url, extend_data=extend_data)

    def push_for_bili_live(self, uname=None, room_id=None, room_title=None, room_cover_url=None, avatar_url=None):
        """
        哔哩哔哩直播提醒推送（支持免打扰）
        """
        title = "【开播提醒-哔哩哔哩】"
        content_before = f"[{uname}]开播啦~"
        content_after = f"\n{room_title}\n\n直播间地址：https://live.bilibili.com/{room_id}/"

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

        super().push(title, "", None, room_cover_url, extend_data=extend_data)

    def push_for_bili_live_end(self, uname=None, uid=None, room_title=None, avatar_url=None):
        """
        哔哩哔哩下播提醒推送（支持免打扰）
        """
        if uname is None or uid is None:
            log.error(f"【哔哩哔哩-下播提醒推送-{self.name}】缺少参数 uname 或 uid")
            return

        start_time = self.live_start_time_dict.get(uid)
        if start_time is None:
            duration_text = "未知"
            log.warning(f"【哔哩哔哩-下播提醒推送-{self.name}】【{uname}】未找到开播时间戳，可能是程序启动前已开播")
        else:
            end_time = time.time()
            duration_seconds = int(end_time - start_time)
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            start_str = time.strftime("%H:%M", time.localtime(start_time))
            end_str = time.strftime("%H:%M", time.localtime(end_time))
            if hours == 0:
                duration_str = f"0小时{minutes}分钟"
            elif minutes == 0:
                duration_str = f"{hours}小时0分钟"
            else:
                duration_str = f"{hours}小时{minutes}分钟"
            duration_text = f"{start_str}~{end_str}({duration_str})"

        content = f"[{uname}]下播啦！\n直播时长：{duration_text}"

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

        super().push("【下播提醒-哔哩哔哩】", content, None, None, extend_data=extend_data)
