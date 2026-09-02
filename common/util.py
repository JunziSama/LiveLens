import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from fake_useragent import UserAgent

from common.logger import log
from common.proxy import my_proxy


DEFAULT_TIMEOUT = (5, 20)
DEFAULT_MAX_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.SSLError,
    requests.exceptions.Timeout,
)

ua = UserAgent(
    os=["windows", "macos", "linux"],
    browsers=["chrome", "edge", "firefox"],
    min_version=120.0,
    fallback="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
)

# Keep one browser identity for the life of the process instead of changing it
# between related requests.
_DEFAULT_USER_AGENT = ua.chrome
_DEFAULT_SESSION = requests.Session()


def _get_random_useragent():
    """Compatibility wrapper that now returns the process-stable user agent."""
    return _DEFAULT_USER_AGENT


def requests_get(
    url,
    module_name="未指定",
    headers=None,
    params=None,
    use_proxy=False,
    session=None,
    retryable=True,
    timeout=DEFAULT_TIMEOUT,
):
    return _request(
        "GET",
        url,
        module_name=module_name,
        headers=headers,
        params=params,
        use_proxy=use_proxy,
        session=session,
        retryable=retryable,
        timeout=timeout,
    )


def requests_post(
    url,
    module_name="未指定",
    headers=None,
    params=None,
    data=None,
    json=None,
    use_proxy=False,
    session=None,
    retryable=False,
    timeout=DEFAULT_TIMEOUT,
):
    return _request(
        "POST",
        url,
        module_name=module_name,
        headers=headers,
        params=params,
        data=data,
        json=json,
        use_proxy=use_proxy,
        session=session,
        retryable=retryable,
        timeout=timeout,
    )


def _request(
    method,
    url,
    module_name,
    headers=None,
    params=None,
    data=None,
    json=None,
    use_proxy=False,
    session=None,
    retryable=False,
    timeout=DEFAULT_TIMEOUT,
):
    request_headers = dict(headers or {})
    if not any(key.lower() == "user-agent" for key in request_headers):
        request_headers["User-Agent"] = _DEFAULT_USER_AGENT
    proxies = _get_proxy() if use_proxy else None
    client = session or _DEFAULT_SESSION
    max_attempts = DEFAULT_MAX_ATTEMPTS if retryable else 1

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.request(
                method,
                url,
                headers=request_headers,
                params=params,
                data=data,
                json=json,
                proxies=proxies,
                timeout=timeout,
                verify=True,
            )
        except RETRYABLE_EXCEPTIONS as exc:
            if attempt >= max_attempts:
                log.error(
                    f"【{module_name}】请求失败，已尝试 {attempt} 次: {exc}",
                    exc_info=True,
                )
                return None
            delay = _retry_delay(attempt)
            log.warning(
                f"【{module_name}】网络异常: {exc}，{delay:.2f} 秒后"
                f"进行第 {attempt + 1}/{max_attempts} 次尝试"
            )
            time.sleep(delay)
            continue
        except requests.exceptions.RequestException as exc:
            log.error(f"【{module_name}】请求失败: {exc}", exc_info=True)
            return None

        if response.status_code not in RETRYABLE_STATUS_CODES or attempt >= max_attempts:
            return response

        delay = _retry_delay(attempt, response)
        log.warning(
            f"【{module_name}】返回可重试状态码 {response.status_code}，"
            f"{delay:.2f} 秒后进行第 {attempt + 1}/{max_attempts} 次尝试"
        )
        response.close()
        time.sleep(delay)

    return None


def _retry_delay(attempt, response=None):
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 30.0))
            except ValueError:
                try:
                    retry_time = parsedate_to_datetime(retry_after)
                    if retry_time.tzinfo is None:
                        retry_time = retry_time.replace(tzinfo=timezone.utc)
                    seconds = (retry_time - datetime.now(timezone.utc)).total_seconds()
                    return max(0.0, min(seconds, 30.0))
                except (TypeError, ValueError, OverflowError):
                    pass
    base_delay = 0.5 * (2 ** (attempt - 1))
    return base_delay + random.uniform(0, 0.25)


def _get_proxy():
    proxy_ip = my_proxy.current_proxy_ip
    if proxy_ip is None:
        return None
    proxy_url = f"http://{proxy_ip}"
    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def check_response_is_ok(response=None):
    if response is None:
        return False
    if response.status_code != requests.codes.OK:
        log.error(f"status: {response.status_code}, url: {response.url}")
        return False
    return True
