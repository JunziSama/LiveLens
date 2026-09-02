import time
import os
from pathlib import Path

import schedule
import yaml

import push_channel
import query_task
from common.config import global_config
from common.logger import log
from common.startup_notification import send_startup_notification

# 配置文件路径
CONFIG_FILE_PATH = Path(__file__).parent / "config.yml"

# 全局任务实例缓存
_bilibili_task = None
_douyu_task = None
_last_config_mtime = 0

def get_config_mtime():
    """获取 config.yml 的最后修改时间"""
    if CONFIG_FILE_PATH.exists():
        return os.path.getmtime(CONFIG_FILE_PATH)
    return 0

def reload_config_if_changed():
    """如果配置文件已更新，则重新加载任务配置"""
    global _last_config_mtime, _bilibili_task, _douyu_task
    current_mtime = get_config_mtime()
    if current_mtime <= _last_config_mtime:
        return
    log.info("检测到 config.yml 已更新，正在热加载配置...")
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            new_config = yaml.safe_load(f)
        # 重新加载 B站任务配置
        for task_cfg in new_config.get('query_task', []):
            if not task_cfg.get('enable', False):
                continue
            if task_cfg.get('type') == 'bilibili' and _bilibili_task:
                # 更新 Cookie 和 payload
                new_cookie = task_cfg.get('cookie', '')
                if new_cookie != _bilibili_task.cookie:
                    _bilibili_task.cookie = new_cookie
                    log.info("B站任务 Cookie 已更新")
                new_payload = task_cfg.get('payload', '')
                if new_payload != _bilibili_task.payload:
                    _bilibili_task.payload = new_payload
                    log.info("B站任务 Payload 已更新")
                # 可选：更新其他配置（如 at_qq 等）
                # 注意：此处未更新免打扰等高级配置，如需更新可继续添加
            elif task_cfg.get('type') == 'douyu' and _douyu_task:
                new_cookie = task_cfg.get('cookie', '')
                # 斗鱼任务没有 cookie 字段？实际斗鱼不需要 cookie，忽略
                pass
        _last_config_mtime = current_mtime
    except Exception as e:
        log.error(f"热加载配置文件失败: {e}")

def init_push_channel(push_channel_config_list: list):
    log.info("开始初始化推送通道")
    for config in push_channel_config_list:
        if config.get('enable', False):
            if push_channel.push_channel_dict.get(config.get('name', '')) is not None:
                raise ValueError(f"推送通道名称重复: {config.get('name', '')}")
            log.info(f"初始化推送通道: {config.get('name', '')}，通道类型: {config.get('type', None)}")
            push_channel.push_channel_dict[config.get('name', '')] = push_channel.get_push_channel(config)

def close_push_channels():
    """关闭推送通道持有的连接等资源。"""
    for channel_name, channel in push_channel.push_channel_dict.items():
        try:
            channel.close()
        except Exception as exc:
            log.warning(f"关闭推送通道【{channel_name}】时出现异常: {exc}")

def init_query_task(query_task_config_list: list):
    global _bilibili_task, _douyu_task, _last_config_mtime
    log.info("初始化查询任务")
    for config in query_task_config_list:
        if config.get('enable', False):
            task = query_task.get_query_task(config)
            if task.type == 'bilibili':
                _bilibili_task = task
            elif task.type == 'douyu':
                _douyu_task = task
            # 启动调度
            schedule.every(config.get("intervals_second", 60)).seconds.do(task.query)
            log.info(f"初始化查询任务: {config.get('name', '')}，任务类型: {config.get('type', None)}")
            # 先执行一次
            task.query()
    # 记录初始配置修改时间
    _last_config_mtime = get_config_mtime()

    while True:
        schedule.run_pending()
        # 每次循环检查配置文件是否更新
        reload_config_if_changed()
        time.sleep(1)

def main():
    common_config = global_config.get_common_config()
    query_task_config_list = global_config.get_query_task_config()
    push_channel_config_list = global_config.get_push_channel_config()
    try:
        # 初始化推送通道
        init_push_channel(push_channel_config_list)
        # 推送可配置的启动成功通知
        send_startup_notification(
            common_config,
            push_channel.push_channel_dict,
            Path(__file__).parent,
        )
        # 初始化查询任务（会进入调度循环）
        init_query_task(query_task_config_list)
    except KeyboardInterrupt:
        log.info("收到退出信号，正在关闭推送通道")
    finally:
        close_push_channels()

if __name__ == '__main__':
    main()
