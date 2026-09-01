import json
import queue
import random
import threading
import time
import uuid
from typing import Callable, Optional

from websockets.sync.client import connect

from common.logger import log


class OneBotWebSocketError(RuntimeError):
    """Base error raised by the OneBot WebSocket client."""


class OneBotConnectionError(OneBotWebSocketError):
    """The client couldn't establish or maintain a connection."""


class OneBotCallTimeout(OneBotWebSocketError):
    """NapCat didn't answer an API request before its deadline."""


class OneBotDeliveryUncertain(OneBotWebSocketError):
    """The connection dropped after a request may have been delivered."""


class OneBotWebSocketClient:
    """Thread-safe synchronous OneBot 11 forward WebSocket client."""

    def __init__(
        self,
        url: str,
        token: str = "",
        connect_timeout: float = 5,
        ping_interval: float = 20,
        ping_timeout: float = 20,
        reconnect_min_seconds: float = 1,
        reconnect_max_seconds: float = 30,
        event_handler: Optional[Callable[[dict], None]] = None,
        name: str = "OneBot",
    ):
        self.url = url
        self.token = token
        self.connect_timeout = connect_timeout
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.reconnect_min_seconds = reconnect_min_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self.event_handler = event_handler
        self.name = name

        self._connected = threading.Event()
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._connection = None
        self._thread = None
        self._permanent_error = None

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        with self._state_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._permanent_error = None
            self._thread = threading.Thread(
                target=self._connection_loop,
                name=f"{self.name}-ws",
                daemon=True,
            )
            self._thread.start()

    def call(self, action: str, params=None, timeout: float = 30) -> dict:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self.start()
        deadline = time.monotonic() + timeout
        if not self._wait_until_connected(deadline):
            if self._permanent_error:
                raise OneBotConnectionError(str(self._permanent_error))
            raise OneBotConnectionError(
                f"连接 {self.url} 超时，无法调用 OneBot 动作 {action}"
            )

        echo = uuid.uuid4().hex
        response_queue = queue.Queue(maxsize=1)
        payload = json.dumps(
            {"action": action, "params": params or {}, "echo": echo},
            ensure_ascii=False,
        )

        with self._pending_lock:
            self._pending[echo] = response_queue

        try:
            with self._send_lock:
                connection = self._connection
                if connection is None or not self._connected.is_set():
                    raise OneBotConnectionError("WebSocket 尚未连接")
                try:
                    connection.send(payload)
                except Exception as exc:
                    raise OneBotDeliveryUncertain(
                        f"发送 {action} 时连接断开，消息是否送达无法确认"
                    ) from exc

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            try:
                result = response_queue.get(timeout=remaining)
            except queue.Empty as exc:
                raise OneBotCallTimeout(
                    f"等待 OneBot 动作 {action} 响应超时"
                ) from exc
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            with self._pending_lock:
                self._pending.pop(echo, None)

    def close(self) -> None:
        self._stop.set()
        self._connected.clear()
        with self._state_lock:
            connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        self._fail_pending(OneBotConnectionError("WebSocket 客户端已关闭"))
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _wait_until_connected(self, deadline: float) -> bool:
        while not self._stop.is_set():
            if self._connected.is_set():
                return True
            if self._permanent_error:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._connected.wait(min(0.1, remaining))
        return False

    def _connection_loop(self) -> None:
        delay = self.reconnect_min_seconds
        while not self._stop.is_set():
            try:
                headers = {}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"
                connection = connect(
                    self.url,
                    additional_headers=headers,
                    open_timeout=self.connect_timeout,
                    close_timeout=5,
                )
                with self._state_lock:
                    self._connection = connection
                self._connected.set()
                delay = self.reconnect_min_seconds
                log.info(f"【推送_{self.name}】NapCat WebSocket 已连接")

                while not self._stop.is_set():
                    try:
                        message = connection.recv(timeout=self.ping_interval)
                    except TimeoutError:
                        pong = connection.ping()
                        if not pong.wait(self.ping_timeout):
                            raise OneBotConnectionError("WebSocket Ping 响应超时")
                        continue
                    if message is None:
                        break
                    if self._stop.is_set():
                        break
                    self._handle_message(message)
            except Exception as exc:
                if self._stop.is_set():
                    break
                self._disconnect(
                    OneBotDeliveryUncertain(
                        "WebSocket 连接中断，等待中的消息是否送达无法确认"
                    )
                )
                if self._is_permanent_connection_error(exc):
                    self._permanent_error = exc
                    log.error(f"【推送_{self.name}】WebSocket 配置或鉴权错误: {exc}")
                    break
                wait_seconds = min(delay, self.reconnect_max_seconds)
                wait_seconds += random.uniform(0, min(1, wait_seconds * 0.2))
                log.warning(
                    f"【推送_{self.name}】WebSocket 连接中断: {exc}，"
                    f"{wait_seconds:.1f} 秒后重连"
                )
                if self._stop.wait(wait_seconds):
                    break
                delay = min(delay * 2, self.reconnect_max_seconds)
            finally:
                self._disconnect(
                    OneBotDeliveryUncertain(
                        "WebSocket 连接中断，等待中的消息是否送达无法确认"
                    )
                )

    def _handle_message(self, message) -> None:
        try:
            data = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            log.warning(f"【推送_{self.name}】忽略无法解析的 WebSocket 消息")
            return
        if not isinstance(data, dict):
            return

        echo = data.get("echo")
        if echo is not None:
            with self._pending_lock:
                response_queue = self._pending.get(str(echo))
            if response_queue is not None:
                try:
                    response_queue.put_nowait(data)
                except queue.Full:
                    pass
                return

        if data.get("post_type"):
            if self.event_handler:
                try:
                    self.event_handler(data)
                except Exception as exc:
                    log.warning(f"【推送_{self.name}】事件处理失败: {exc}")
            else:
                log.debug(f"【推送_{self.name}】收到并忽略 OneBot 事件")

    def _fail_pending(self, error: Exception) -> None:
        with self._pending_lock:
            response_queues = list(self._pending.values())
        for response_queue in response_queues:
            try:
                response_queue.put_nowait(error)
            except queue.Full:
                pass

    def _disconnect(self, error: Exception) -> None:
        self._connected.clear()
        with self._state_lock:
            connection = self._connection
            self._connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        if not self._stop.is_set():
            self._fail_pending(error)

    @staticmethod
    def _is_permanent_connection_error(exc: Exception) -> bool:
        if exc.__class__.__name__ == "InvalidURI":
            return True
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        return status_code is not None and 400 <= status_code < 500
