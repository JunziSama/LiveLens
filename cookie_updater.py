import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import qrcode
import requests
import yaml

from common import util


CONFIG_FILE_PATH = Path(__file__).parent / "config.yml"
BACKUP_FILE_PATH = CONFIG_FILE_PATH.with_suffix(".yml.bak")
QRCODE_FILE_PATH = Path(__file__).parent / "qrcode.png"
LOGIN_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 2
MIN_QRCODE_CONSOLE_COLUMNS = 120
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class CookieUpdaterError(RuntimeError):
    """Base error for expected Cookie updater failures."""


class LoginExpiredError(CookieUpdaterError):
    """The Bilibili login QR code expired."""


class LoginTimeoutError(CookieUpdaterError):
    """The login wasn't completed before the overall deadline."""


def create_session():
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.bilibili.com/",
            "User-Agent": USER_AGENT,
        }
    )
    return session


def _response_json(response, operation):
    if response is None:
        return None
    if response.status_code == 412:
        print(f"{operation}触发 B站 412 风控，将继续尝试。")
        return None
    if response.status_code != 200:
        print(f"{operation}返回 HTTP {response.status_code}，将继续尝试。")
        return None
    content_type = response.headers.get("Content-Type", "").lower()
    if "json" not in content_type:
        print(f"{operation}返回了非 JSON 内容，将继续尝试。")
        return None
    try:
        result = response.json()
    except (requests.exceptions.JSONDecodeError, ValueError):
        print(f"{operation}返回的 JSON 无法解析，将继续尝试。")
        return None
    if not isinstance(result, dict):
        print(f"{operation}返回的数据结构无效，将继续尝试。")
        return None
    if result.get("code") != 0:
        message = result.get("message") or "未知错误"
        print(f"{operation}失败：{message}")
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        print(f"{operation}响应缺少 data 字段。")
        return None
    return data


def get_qrcode(session):
    response = util.requests_get(
        "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
        "B站二维码生成",
        session=session,
        retryable=True,
        timeout=(5, 10),
    )
    data = _response_json(response, "二维码生成")
    if data is None:
        raise CookieUpdaterError("无法生成登录二维码，请稍后重试")
    login_url = data.get("url")
    qrcode_key = data.get("qrcode_key")
    if not isinstance(login_url, str) or not login_url:
        raise CookieUpdaterError("二维码响应中缺少登录地址")
    if not isinstance(qrcode_key, str) or not qrcode_key:
        raise CookieUpdaterError("二维码响应中缺少登录密钥")
    return login_url, qrcode_key


def build_qrcode(login_url):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(login_url)
    qr.make(fit=True)
    return qr


def save_qrcode_image(qr, image_path=QRCODE_FILE_PATH):
    image_path = Path(image_path)
    image = qr.make_image(fill_color="black", back_color="white")
    image.save(image_path)
    return image_path.absolute()


def open_qrcode_image(image_path):
    image_path = Path(image_path).absolute()
    if not hasattr(os, "startfile"):
        print(f"当前系统无法自动打开图片，请手动查看：{image_path}")
        return False
    try:
        os.startfile(str(image_path))
    except OSError as exc:
        print(f"无法打开二维码图片：{exc}")
        print(f"请手动查看：{image_path}")
        return False
    print("已在图片查看器中打开二维码，控制台仍会继续等待扫码。")
    return True


def _render_console_qrcode(qr, output, terminal_columns=0):
    """Render a square QR code without the half-block glyphs used by qrcode."""
    matrix = qr.get_matrix()
    if not matrix or not matrix[0]:
        raise ValueError("二维码矩阵为空")

    matrix_width = len(matrix[0])
    if any(len(row) != matrix_width for row in matrix):
        raise ValueError("二维码矩阵尺寸无效")

    required_columns = matrix_width * 2
    if terminal_columns and terminal_columns < required_columns:
        return False, required_columns

    # Cookie.bat uses the standard dark console theme. Two full blocks paint a
    # light module, while two spaces expose the dark background for a QR module.
    for row in matrix:
        output.write("".join("  " if module else "██" for module in row))
        output.write("\n")
    output.flush()
    return True, required_columns


def _resize_windows_console(required_columns, terminal_size_getter=None):
    """Try to widen an interactive Windows console and return its new width."""
    terminal_size_getter = terminal_size_getter or (
        lambda: shutil.get_terminal_size(fallback=(0, 0)).columns
    )
    current_columns = terminal_size_getter()
    if os.name != "nt":
        return current_columns

    target_columns = max(MIN_QRCODE_CONSOLE_COLUMNS, required_columns)
    try:
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", f"mode con cols={target_columns}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return current_columns
    if result.returncode != 0:
        return current_columns
    return terminal_size_getter()


def display_qrcode(
    qr,
    image_path,
    output=None,
    interactive=None,
    image_opener=open_qrcode_image,
    terminal_columns=None,
    console_resizer=None,
):
    output = output or sys.stdout
    if interactive is None:
        interactive = bool(getattr(output, "isatty", lambda: False)())
    if terminal_columns is None:
        terminal_columns = shutil.get_terminal_size(fallback=(0, 0)).columns
    console_resizer = console_resizer or _resize_windows_console

    print("\n请使用 B站 APP 的【扫一扫】扫描以下二维码：", file=output)
    rendered = False
    required_columns = 0
    try:
        rendered, required_columns = _render_console_qrcode(
            qr,
            output,
            terminal_columns=terminal_columns,
        )
        if not rendered and interactive:
            terminal_columns = console_resizer(required_columns)
            rendered, required_columns = _render_console_qrcode(
                qr,
                output,
                terminal_columns=terminal_columns,
            )
        if not rendered and terminal_columns:
            print(
                f"控制台宽度不足：当前 {terminal_columns} 列，"
                f"二维码至少需要 {required_columns} 列。",
                file=output,
            )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"控制台二维码显示失败：{exc}", file=output)

    print(f"备用二维码图片：{Path(image_path).absolute()}", file=output)
    if rendered:
        print("按 O 打开备用图片；按 R 重新绘制二维码；按 Ctrl+C 取消。", file=output)
    else:
        print("请手动扩大窗口后按 R 重新绘制；按 O 打开备用图片。", file=output)
        print("也可直接进入上述路径所在文件夹打开 qrcode.png。", file=output)
    output.flush()
    return rendered


def read_console_key():
    if os.name != "nt":
        return None
    try:
        import msvcrt

        if msvcrt.kbhit():
            return msvcrt.getwch()
    except (ImportError, OSError):
        return None
    return None


def _extract_login_cookie(session, response):
    cookies = session.cookies.get_dict()
    cookies.update(response.cookies.get_dict())
    sessdata = cookies.get("SESSDATA", "")
    bili_jct = cookies.get("bili_jct", "")
    dedeuserid = cookies.get("DedeUserID", "")
    if not (sessdata and bili_jct and dedeuserid):
        raise CookieUpdaterError("登录成功，但响应中缺少必要 Cookie 字段")
    return sessdata, bili_jct, dedeuserid


def poll_login(
    session,
    qrcode_key,
    image_path,
    timeout=LOGIN_TIMEOUT_SECONDS,
    poll_interval=POLL_INTERVAL_SECONDS,
    key_reader=read_console_key,
    image_opener=open_qrcode_image,
    redraw_callback=None,
    clock=time.monotonic,
    sleeper=time.sleep,
):
    poll_url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    deadline = clock() + timeout
    last_status = None

    while clock() < deadline:
        key = key_reader()
        if key:
            normalized_key = key.lower()
            if normalized_key == "o":
                image_opener(image_path)
            elif normalized_key == "r" and redraw_callback is not None:
                redraw_callback()

        response = util.requests_get(
            poll_url,
            "B站二维码登录轮询",
            params={"qrcode_key": qrcode_key},
            session=session,
            retryable=True,
            timeout=(5, 10),
        )
        data = _response_json(response, "登录状态查询")
        if data is None:
            if last_status != "network":
                print("登录状态暂时无法获取，将在二维码有效期内继续尝试...")
                last_status = "network"
            sleeper(poll_interval)
            continue

        code = data.get("code")
        if code != last_status:
            if code == 86101:
                print("等待扫码...")
            elif code == 86090:
                print("已扫码，等待手机确认...")
            elif code == 86038:
                raise LoginExpiredError("二维码已过期，请重新运行 Cookie.bat")
            elif code == 0:
                print("登录成功，正在校验凭证...")
            else:
                print(f"登录状态异常：{data.get('message') or code}")
            last_status = code

        if code == 0:
            return _extract_login_cookie(session, response)
        sleeper(poll_interval)

    raise LoginTimeoutError("扫码登录超时，请重新运行 Cookie.bat")


def validate_cookie_format(cookie_str):
    required = ["SESSDATA=", "bili_jct=", "DedeUserID="]
    if not all(key in cookie_str for key in required):
        return False
    return len([part for part in cookie_str.split(";") if part.strip()]) >= 3


def build_cookie_string(sessdata, bili_jct, dedeuserid):
    return f"SESSDATA={sessdata}; bili_jct={bili_jct}; DedeUserID={dedeuserid}"


def _find_bilibili_cookie_line(lines):
    section_start = None
    section_end = len(lines)
    section_indent = 0

    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)query_task\s*:\s*(?:#.*)?$", line)
        if match:
            section_start = index
            section_indent = len(match.group(1))
            break
    if section_start is None:
        raise CookieUpdaterError("配置中缺少 query_task")

    for index in range(section_start + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(lines[index]) - len(lines[index].lstrip())
        if indent <= section_indent:
            section_end = index
            break

    list_items = []
    for index in range(section_start + 1, section_end):
        line = lines[index]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent > section_indent and stripped.startswith("- "):
            list_items.append((index, indent))
    if not list_items:
        raise CookieUpdaterError("query_task 中没有可用的查询任务")

    task_indent = min(indent for _, indent in list_items)
    item_starts = [index for index, indent in list_items if indent == task_indent]
    item_starts.append(section_end)

    matching_lines = []
    for position in range(len(item_starts) - 1):
        start = item_starts[position]
        end = item_starts[position + 1]
        block = lines[start:end]
        type_field_indents = []
        for line in block:
            match = re.match(
                r"^(\s*)(-\s*)?type\s*:\s*['\"]?bilibili['\"]?\s*(?:#.*)?(?:\r?\n)?$",
                line,
            )
            if match:
                key_indent = len(match.group(1)) + (2 if match.group(2) else 0)
                type_field_indents.append(key_indent)
        if not type_field_indents:
            continue
        if len(type_field_indents) != 1:
            raise CookieUpdaterError("Bilibili 任务必须且只能包含一个 type 字段")

        field_indent = type_field_indents[0]
        cookie_lines = [
            start + offset
            for offset, line in enumerate(block)
            if (
                len(line) - len(line.lstrip()) == field_indent
                and re.match(r"^\s*cookie\s*:", line)
            )
        ]
        if len(cookie_lines) != 1:
            raise CookieUpdaterError("Bilibili 任务必须且只能包含一个 cookie 字段")
        matching_lines.extend(cookie_lines)

    if len(matching_lines) == 0:
        raise CookieUpdaterError("未找到 type: bilibili 的查询任务")
    if len(matching_lines) > 1:
        raise CookieUpdaterError("检测到多个 Bilibili 查询任务，无法确定要更新的 Cookie")
    return matching_lines[0]


def _get_bilibili_task(config):
    tasks = config.get("query_task") if isinstance(config, dict) else None
    if not isinstance(tasks, list):
        raise CookieUpdaterError("配置缺少 query_task 列表")
    bilibili_tasks = [
        task for task in tasks if isinstance(task, dict) and task.get("type") == "bilibili"
    ]
    if len(bilibili_tasks) != 1:
        raise CookieUpdaterError("配置中必须且只能存在一个 Bilibili 查询任务")
    if "cookie" not in bilibili_tasks[0]:
        raise CookieUpdaterError("Bilibili 查询任务缺少 cookie 字段")
    return bilibili_tasks[0]


def _validate_config_structure(config, expected_cookie):
    bilibili_task = _get_bilibili_task(config)
    if bilibili_task.get("cookie") != expected_cookie:
        raise CookieUpdaterError("更新后的 Cookie 校验失败")


def validate_cookie_update_target(config_path=CONFIG_FILE_PATH):
    config_path = Path(config_path)
    if not config_path.is_file():
        raise CookieUpdaterError(f"配置文件不存在：{config_path}")
    with config_path.open("r", encoding="utf-8-sig", newline="") as file:
        lines = file.readlines()
    cookie_line = _find_bilibili_cookie_line(lines)
    try:
        config = yaml.safe_load("".join(lines))
    except yaml.YAMLError as exc:
        raise CookieUpdaterError("配置文件不是有效的 YAML") from exc
    _get_bilibili_task(config)
    return cookie_line


def update_cookie_in_file(
    new_cookie_value,
    config_path=CONFIG_FILE_PATH,
    backup_path=None,
):
    config_path = Path(config_path)
    backup_path = Path(backup_path) if backup_path else config_path.with_suffix(".yml.bak")
    if not config_path.is_file():
        raise CookieUpdaterError(f"配置文件不存在：{config_path}")
    if not validate_cookie_format(new_cookie_value):
        raise CookieUpdaterError("生成的 Cookie 缺少必要字段")

    with config_path.open("r", encoding="utf-8-sig", newline="") as file:
        lines = file.readlines()
    cookie_line = _find_bilibili_cookie_line(lines)
    original_line = lines[cookie_line]
    line_match = re.match(
        r"^(\s*cookie\s*:\s*)(.*?)([ \t]+#.*)?(\r\n|\n)?$",
        original_line,
    )
    if line_match is None:
        raise CookieUpdaterError("无法解析 Bilibili Cookie 配置行")
    prefix = line_match.group(1)
    inline_comment = line_match.group(3) or ""
    line_ending = line_match.group(4) or ""
    lines[cookie_line] = (
        f"{prefix}{json.dumps(new_cookie_value, ensure_ascii=False)}"
        f"{inline_comment}{line_ending}"
    )

    temp_path = config_path.with_name(f".{config_path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="") as file:
            file.writelines(lines)
            file.flush()
            os.fsync(file.fileno())
        with temp_path.open("r", encoding="utf-8") as file:
            updated_config = yaml.safe_load(file)
        _validate_config_structure(updated_config, new_cookie_value)
        shutil.copymode(config_path, temp_path)
        shutil.copy2(config_path, backup_path)
        os.replace(temp_path, config_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return backup_path


def remove_qrcode(image_path=QRCODE_FILE_PATH, quiet=False):
    image_path = Path(image_path)
    try:
        image_path.unlink(missing_ok=True)
        return True
    except OSError as exc:
        if not quiet:
            print(f"二维码图片暂时无法删除：{exc}")
            print(f"请稍后手动删除：{image_path.absolute()}")
        return False


def main(config_path=CONFIG_FILE_PATH, image_path=QRCODE_FILE_PATH):
    remove_qrcode(image_path, quiet=True)
    session = None
    try:
        print("正在检查本地 Bilibili 配置...")
        validate_cookie_update_target(config_path)
        session = create_session()
        print("正在生成二维码...")
        login_url, qrcode_key = get_qrcode(session)
        qr = build_qrcode(login_url)
        saved_path = save_qrcode_image(qr, image_path)
        display_qrcode(qr, saved_path)

        credentials = poll_login(
            session,
            qrcode_key,
            saved_path,
            redraw_callback=lambda: display_qrcode(qr, saved_path),
        )
        new_cookie = build_cookie_string(*credentials)
        backup_path = update_cookie_in_file(new_cookie, config_path=config_path)
        print("Cookie 格式验证通过。")
        print(f"Cookie 已安全更新到：{Path(config_path).absolute()}")
        print(f"原配置备份位于：{Path(backup_path).absolute()}")
        print("LiveLens 正在运行时会自动热加载；否则将在下次启动时生效。")
        return 0
    except KeyboardInterrupt:
        print("\n已取消 Cookie 获取。")
        return 130
    except LoginExpiredError as exc:
        print(f"Cookie 获取失败：{exc}")
        return 2
    except LoginTimeoutError as exc:
        print(f"Cookie 获取失败：{exc}")
        return 3
    except CookieUpdaterError as exc:
        print(f"Cookie 获取失败：{exc}")
        return 1
    except Exception as exc:
        print(f"Cookie 获取发生未预期错误：{exc}")
        return 1
    finally:
        if session is not None:
            session.close()
        remove_qrcode(image_path)


def cli(argv=None):
    parser = argparse.ArgumentParser(description="Bilibili Cookie 获取工具")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="只读检查 Bilibili Cookie 配置定位，不发起登录",
    )
    args = parser.parse_args(argv)
    if not args.check_config:
        return main()
    try:
        validate_cookie_update_target(CONFIG_FILE_PATH)
    except CookieUpdaterError as exc:
        print(f"Bilibili Cookie 配置检查失败：{exc}")
        return 1
    print("Bilibili Cookie 配置检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
