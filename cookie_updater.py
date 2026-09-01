import time
import re
import os
import shutil
from pathlib import Path

import requests
import yaml

CONFIG_FILE_PATH = Path(__file__).parent / "config.yml"
BACKUP_FILE_PATH = CONFIG_FILE_PATH.with_suffix(".yml.bak")

def install_qrcode():
    try:
        import qrcode
        from PIL import Image
        return qrcode, Image
    except ImportError:
        print("缺少二维码生成库，请运行: pip install qrcode pillow")
        exit(1)

def get_qrcode():
    url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    data = resp.json()['data']
    return data['url'], data['qrcode_key']

def save_qrcode_image(url, filename="qrcode.png"):
    qrcode, Image = install_qrcode()
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(filename)
    return str(Path(filename).absolute())

def poll_login(qrcode_key, timeout=120):
    poll_url = f"https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={qrcode_key}"
    start_time = time.time()
    last_status = None
    while time.time() - start_time < timeout:
        resp = requests.get(poll_url, headers={"User-Agent": "Mozilla/5.0"})
        data = resp.json()
        code = data['data']['code']
        if code != last_status:
            if code == 86101:
                print("等待扫码...")
            elif code == 86090:
                print("已扫码，等待确认...")
            elif code == 86038:
                print("二维码已过期")
                return None
            elif code == 0:
                print("登录成功！正在获取凭证...")
            else:
                print(f"状态码: {code}")
            last_status = code
        if code == 0:
            cookies = resp.cookies.get_dict()
            sessdata = cookies.get('SESSDATA', '')
            bili_jct = cookies.get('bili_jct', '')
            dedeuserid = cookies.get('DedeUserID', '')
            if sessdata and bili_jct:
                return sessdata, bili_jct, dedeuserid
        time.sleep(2)
    return None

def find_bilibili_task_line(lines):
    """返回 B站任务的起始行索引和 cookie 行的索引（基于0）"""
    in_bilibili_task = False
    task_start = -1
    cookie_line_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('- name:') and '任务_bilibili' in line:
            in_bilibili_task = True
            task_start = i
            continue
        if in_bilibili_task and stripped.startswith('cookie:'):
            cookie_line_idx = i
        # 退出条件：遇到下一个 '-' 并且不是当前任务
        if in_bilibili_task and stripped.startswith('- name:') and i > task_start:
            break
    return task_start, cookie_line_idx

def validate_cookie_format(cookie_str: str) -> bool:
    """
    检查 cookie 字符串是否符合标准格式：
    - 包含 SESSDATA、bili_jct、DedeUserID 三个字段
    - 字段之间用分号+空格分隔
    - 末尾可以有分号也可以没有（宽松）
    """
    required = ['SESSDATA=', 'bili_jct=', 'DedeUserID=']
    for key in required:
        if key not in cookie_str:
            return False
    # 检查分隔符：至少出现两个分号（或一个分号但字段数量足够）
    # 由于末尾分号可选，我们只要求分号数量 >= 2 或者字段之间有明显分隔
    parts = cookie_str.split(';')
    # 去除空字符串后至少有三个部分
    non_empty_parts = [p.strip() for p in parts if p.strip()]
    if len(non_empty_parts) < 3:
        return False
    return True

def update_cookie_in_file(new_cookie_value: str):
    """直接修改 config.yml 文件，保留注释和格式，并在修改前备份"""
    if not CONFIG_FILE_PATH.exists():
        print(f"配置文件不存在: {CONFIG_FILE_PATH}")
        return False

    # 备份原文件
    try:
        shutil.copy2(CONFIG_FILE_PATH, BACKUP_FILE_PATH)
        print(f"已备份原配置文件至: {BACKUP_FILE_PATH}")
    except Exception as e:
        print(f"备份失败: {e}，继续执行...")

    with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    task_start, cookie_line = find_bilibili_task_line(lines)
    if cookie_line == -1:
        print("未找到 B站任务的 cookie 行")
        return False

    # 构造新的 cookie 行（保持缩进）
    orig_line = lines[cookie_line]
    indent = re.match(r'^\s*', orig_line).group()
    # 确保 cookie 值被双引号包裹（YAML 需要，因为值中包含分号和空格）
    new_line = f"{indent}cookie: \"{new_cookie_value}\"\n"
    lines[cookie_line] = new_line

    # 写回文件
    with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    return True

def build_cookie_string(sessdata, bili_jct, dedeuserid):
    """
    构建标准格式的 cookie 字符串（与B站实际返回的格式一致）
    格式: SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx
    末尾不加分号，键值对之间用分号+空格分隔
    """
    return f"SESSDATA={sessdata}; bili_jct={bili_jct}; DedeUserID={dedeuserid}"

def main():
    print("正在生成二维码...")
    url, key = get_qrcode()
    img_path = save_qrcode_image(url)
    print(f"✅ 二维码已保存为图片: {img_path}")

    try:
        os.startfile(img_path)
        print("已自动打开二维码图片，请使用 B站 APP 扫码。")
    except Exception as e:
        print(f"无法自动打开图片（可手动打开）: {e}")

    print("请用手机B站APP的【扫一扫】功能扫描该图片中的二维码，不要手动打开链接。")
    print("扫描后请在手机上确认登录。")
    result = poll_login(key, timeout=120)
    if not result:
        print("扫码登录超时或失败")
        Path(img_path).unlink(missing_ok=True)
        return
    sessdata, bili_jct, dedeuserid = result
    print("登录成功！正在更新配置文件...")
    new_cookie_str = build_cookie_string(sessdata, bili_jct, dedeuserid)

    # 验证格式
    if not validate_cookie_format(new_cookie_str):
        print("警告：生成的 cookie 格式可能不规范，但仍将写入配置文件。")
    else:
        print("Cookie 格式验证通过（标准分号+空格分隔）。")

    if update_cookie_in_file(new_cookie_str):
        print(f"✅ Cookie 已更新到 {CONFIG_FILE_PATH}")
        print("请手动重启主监控程序 (`Live.bat`) 以使新Cookie生效。")
    else:
        print("❌ 更新配置文件失败")

    Path(img_path).unlink(missing_ok=True)
    print("临时二维码文件已删除。")

if __name__ == '__main__':
    main()