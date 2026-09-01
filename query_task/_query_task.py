from abc import ABC, abstractmethod
from collections import deque
import time

import push_channel
from common.logger import log


class QueryTask(ABC):
    def __init__(self, config):
        self.name = config.get("name", "")
        self.enable = config.get("enable", False)
        self.type = config.get("type", "")
        self.intervals_second = config.get("intervals_second", 60)
        self.begin_time = config.get("begin_time", "00:00")
        self.end_time = config.get("end_time", "23:59")
        self.target_push_name_list = config.get("target_push_name_list", [])
        self.enable_dynamic_check = config.get("enable_dynamic_check", False)
        self.enable_living_check = config.get("enable_living_check", False)

        # 任务级别的 @ 设置（全局默认）
        self.at_qq = config.get("at_qq", "")

        # 时长免打扰配置（分钟）
        self.mute_enable_dynamic = config.get("mute_enable_dynamic", False)
        self.mute_minutes_dynamic = config.get("mute_minutes_dynamic", 0)
        self.mute_enable_live = config.get("mute_enable_live", False)
        self.mute_minutes_live = config.get("mute_minutes_live", 0)
        self.mute_enable_live_end = config.get("mute_enable_live_end", False)
        self.mute_minutes_live_end = config.get("mute_minutes_live_end", 0)

        # 时间段免打扰配置（格式如 "0,7;12,14" 或 "00:00,07:00;12:00,14:00"）
        self.mute_time_ranges_dynamic = self._parse_time_ranges(config.get("mute_time_ranges_dynamic", ""))
        self.mute_time_ranges_live = self._parse_time_ranges(config.get("mute_time_ranges_live", ""))
        self.mute_time_ranges_live_end = self._parse_time_ranges(config.get("mute_time_ranges_live_end", ""))

        # 记录上次动作的时间戳（key: group_id_action），用于时长免打扰
        self.last_at_time = {}

        self.len_of_deque = 100
        self.dynamic_dict = {}
        self.living_status_dict = {}

    def _parse_time_ranges(self, ranges_str: str):
        """解析时间段配置，支持 '0,7;12,14' 或 '00:00,07:00;12:00,14:00'"""
        if not ranges_str:
            return []
        ranges = []
        for part in ranges_str.split(';'):
            part = part.strip()
            if not part:
                continue
            if ',' in part:
                start_str, end_str = part.split(',', 1)
            elif '-' in part:
                start_str, end_str = part.split('-', 1)
            else:
                continue
            # 解析开始时间
            if ':' in start_str:
                sh, sm = start_str.split(':')
                start_hour = int(sh)
                start_min = int(sm)
            else:
                start_hour = int(start_str)
                start_min = 0
            # 解析结束时间
            if ':' in end_str:
                eh, em = end_str.split(':')
                end_hour = int(eh)
                end_min = int(em)
            else:
                end_hour = int(end_str)
                end_min = 0
            ranges.append(((start_hour, start_min), (end_hour, end_min)))
        return ranges

    def _is_in_time_ranges(self, ranges):
        """判断当前时间是否在任一时间段内（基于本地时间）"""
        if not ranges:
            return False
        now = time.localtime()
        current_minutes = now.tm_hour * 60 + now.tm_min
        for (start_h, start_m), (end_h, end_m) in ranges:
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            if start_minutes <= current_minutes < end_minutes:
                return True
        return False

    def _get_current_time_range_desc(self, ranges):
        """获取当前时间所属的时间段描述（如 '00:00~07:00'）"""
        now = time.localtime()
        current_minutes = now.tm_hour * 60 + now.tm_min
        for (start_h, start_m), (end_h, end_m) in ranges:
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            if start_minutes <= current_minutes < end_minutes:
                start_str = f"{start_h:02d}:{start_m:02d}"
                end_str = f"{end_h:02d}:{end_m:02d}"
                return f"{start_str}~{end_str}"
        return "未知时间段"

    @staticmethod
    def _format_duration_minutes(minutes: int) -> str:
        """将分钟数格式化为 'x小时y分钟' 格式"""
        hours = minutes // 60
        mins = minutes % 60
        if hours == 0:
            return f"0小时{mins}分钟"
        elif mins == 0:
            return f"{hours}小时0分钟"
        else:
            return f"{hours}小时{mins}分钟"

    @abstractmethod
    def query(self):
        raise NotImplementedError("Subclasses must implement the query method")

    def handle_for_result_null(self, null_id="-1", dict_key=None, module_name="未指定", user_name=None):
        if dict_key is None:
            log.error(f"{module_name}，handle_for_result_null，参数dynamic_dict_key不能为空")
        if user_name is None:
            user_name = dict_key

        if self.dynamic_dict.get(dict_key, None) is None:
            self.dynamic_dict[dict_key] = deque(maxlen=self.len_of_deque)
            self.dynamic_dict[dict_key].append(null_id)
            log.info(f"【{module_name}-查询动态状态-{self.name}】【{user_name}】动态初始化：{self.dynamic_dict[dict_key]}")
        else:
            previous_id = self.dynamic_dict[dict_key].pop()
            self.dynamic_dict[dict_key].append(previous_id)
            if previous_id != null_id:
                log.error(f"【{module_name}-查询动态状态-{self.name}】【{user_name}】动态列表为空")

    def check_mute(self, action: str, group_id: str, at_qq: str):
        """
        检查是否应该免打扰（时长免打扰 + 时间段免打扰）
        :return: (是否免打扰, 提示文本)
        """
        if not at_qq:
            return False, ""

        # 获取该动作的配置
        if action == "dynamic":
            enable_duration = self.mute_enable_dynamic
            duration_minutes = self.mute_minutes_dynamic
            time_ranges = self.mute_time_ranges_dynamic
        elif action == "live":
            enable_duration = self.mute_enable_live
            duration_minutes = self.mute_minutes_live
            time_ranges = self.mute_time_ranges_live
        elif action == "live_end":
            enable_duration = self.mute_enable_live_end
            duration_minutes = self.mute_minutes_live_end
            time_ranges = self.mute_time_ranges_live_end
        else:
            return False, ""

        key = f"{group_id}_{action}"
        now = time.time()

        # 1. 时间段免打扰
        in_time_range = self._is_in_time_ranges(time_ranges)

        # 2. 时长免打扰
        duration_mute = False
        duration_text = ""
        if enable_duration and duration_minutes > 0:
            last = self.last_at_time.get(key, 0)
            if last and (now - last) < (duration_minutes * 60):
                duration_mute = True
                duration_text = self._format_duration_minutes(duration_minutes)

        # 无论是否触发免打扰，只要开启了时长免打扰且 at_qq 非空，就更新本次动作时间戳（用于下次时长判断）
        if enable_duration and duration_minutes > 0:
            self.last_at_time[key] = now

        # 只要满足任一条件即免打扰
        if in_time_range or duration_mute:
            # 构建提示文本
            if in_time_range and duration_mute:
                time_desc = self._get_current_time_range_desc(time_ranges)
                mute_text = f"免打扰（{at_qq}）：{time_desc}({duration_text})"
            elif in_time_range:
                time_desc = self._get_current_time_range_desc(time_ranges)
                mute_text = f"免打扰（{at_qq}）：{time_desc}"
            else:
                mute_text = f"免打扰（{at_qq}）：{duration_text}"
            return True, mute_text
        else:
            return False, ""

    def push(self, title, content, jump_url=None, pic_url=None, extend_data=None):
        for item in self.target_push_name_list:
            target_push_channel = push_channel.push_channel_dict.get(item, None)
            if target_push_channel is None:
                log.error(f"【{self.name}】推送通道【{item}】不存在")
            else:
                try:
                    if extend_data is None:
                        extend_data = {}
                    if 'at_qq' not in extend_data:
                        extend_data['at_qq'] = self.at_qq
                    final_extend_data = {
                        **extend_data,
                        'query_task_config': {
                            'name': self.name,
                            'enable': self.enable,
                            'type': self.type,
                            'intervals_second': self.intervals_second,
                            'begin_time': self.begin_time,
                            'end_time': self.end_time,
                            'target_push_name_list': self.target_push_name_list,
                            'enable_dynamic_check': self.enable_dynamic_check,
                            'enable_living_check': self.enable_living_check,
                        },
                    }
                    if pic_url == '':
                        pic_url = None
                    target_push_channel.push(title, content, jump_url, pic_url, final_extend_data)
                except Exception as e:
                    log.error(f"【{self.name}】推送通道【{item}】出错：{e}", exc_info=True)