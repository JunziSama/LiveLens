import time
import hashlib
from functools import lru_cache
from common import util
from common.logger import log

# WBI 签名密钥映射表（固定）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

@lru_cache(maxsize=1)
def get_wbi_keys() -> tuple:
    """
    从 B站导航接口获取最新的 img_key 和 sub_key
    即使未登录（code=-101）也能获取到 wbi_img，直接提取密钥
    返回 (img_key, sub_key)
    """
    url = "https://api.bilibili.com/x/web-interface/nav"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.bilibili.com/"
    }
    try:
        resp = util.requests_get(
            url,
            "获取WBI密钥",
            headers=headers,
            retryable=True,
            timeout=(5, 10),
        )
        if resp is None:
            raise RuntimeError("获取 WBI 密钥失败")
        if resp.status_code != 200:
            log.error(f"获取WBI密钥失败，状态码: {resp.status_code}")
            raise RuntimeError("获取 WBI 密钥失败")
        data = resp.json()
        # 关键修改：不检查 code，直接尝试提取 wbi_img
        wbi_img = data.get("data", {}).get("wbi_img")
        if not wbi_img:
            log.error(f"获取WBI密钥失败，响应中没有 wbi_img 字段: {data}")
            raise RuntimeError("获取 WBI 密钥失败")
        img_url = wbi_img["img_url"]
        sub_url = wbi_img["sub_url"]
        img_key = img_url.rsplit('/', 1)[-1].split('.')[0]
        sub_key = sub_url.rsplit('/', 1)[-1].split('.')[0]
        log.info("WBI密钥获取成功")
        return img_key, sub_key
    except Exception as e:
        log.error(f"获取WBI密钥异常: {e}")
        raise

def get_mixin_key(orig: str) -> str:
    """对 img_key 或 sub_key 进行重排，生成 mixin_key 前缀"""
    result = []
    for i in MIXIN_KEY_ENC_TAB:
        if i < len(orig):
            result.append(orig[i])
    return ''.join(result)

def encrypt_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """
    对请求参数进行 WBI 签名，返回添加了 wts 和 w_rid 的新字典
    """
    # 合并两个 key 并取前 32 位作为 mixin_key
    mixin_key = get_mixin_key(img_key + sub_key)[:32]
    # 添加当前时间戳（秒）
    params = params.copy()
    params["wts"] = int(time.time())
    # 按键名排序
    sorted_keys = sorted(params.keys())
    # 构建待签名字符串
    query = "&".join([f"{k}={params[k]}" for k in sorted_keys])
    sign_str = query + mixin_key
    # 计算 MD5
    w_rid = hashlib.md5(sign_str.encode()).hexdigest()
    params["w_rid"] = w_rid
    return params
