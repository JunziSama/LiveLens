import unittest
from unittest.mock import Mock, patch

import requests

from common import util


class RequestRetryTest(unittest.TestCase):
    def setUp(self):
        self.sleep_patcher = patch("common.util.time.sleep")
        self.random_patcher = patch("common.util.random.uniform", return_value=0)
        self.sleep = self.sleep_patcher.start()
        self.random_patcher.start()
        self.addCleanup(self.sleep_patcher.stop)
        self.addCleanup(self.random_patcher.stop)

    @staticmethod
    def response(status_code=200, headers=None):
        response = Mock()
        response.status_code = status_code
        response.headers = headers or {}
        return response

    def test_ssl_error_is_retried_then_succeeds(self):
        session = Mock()
        success = self.response()
        session.request.side_effect = [
            requests.exceptions.SSLError("temporary TLS EOF"),
            success,
        ]

        result = util.requests_get(
            "https://example.test",
            "retry-test",
            session=session,
            retryable=True,
        )

        self.assertIs(result, success)
        self.assertEqual(session.request.call_count, 2)
        self.sleep.assert_called_once_with(0.5)

    def test_retry_exhaustion_returns_none(self):
        session = Mock()
        session.request.side_effect = requests.exceptions.ConnectionError("offline")

        result = util.requests_get(
            "https://example.test",
            "retry-test",
            session=session,
            retryable=True,
        )

        self.assertIsNone(result)
        self.assertEqual(session.request.call_count, 3)

    def test_retry_after_is_honored_for_429(self):
        session = Mock()
        limited = self.response(429, {"Retry-After": "0"})
        success = self.response()
        session.request.side_effect = [limited, success]

        result = util.requests_post(
            "https://example.test",
            "retry-test",
            json={"query": True},
            session=session,
            retryable=True,
        )

        self.assertIs(result, success)
        limited.close.assert_called_once_with()
        self.sleep.assert_called_once_with(0.0)

    def test_non_retryable_412_is_returned_immediately(self):
        session = Mock()
        blocked = self.response(412)
        session.request.return_value = blocked

        result = util.requests_get(
            "https://example.test",
            "retry-test",
            session=session,
            retryable=True,
        )

        self.assertIs(result, blocked)
        session.request.assert_called_once()

    def test_existing_lowercase_user_agent_is_preserved(self):
        session = Mock()
        session.request.return_value = self.response()

        util.requests_get(
            "https://example.test",
            "header-test",
            headers={"user-agent": "stable-browser"},
            session=session,
        )

        headers = session.request.call_args.kwargs["headers"]
        self.assertEqual(headers, {"user-agent": "stable-browser"})

    def test_https_proxy_uses_the_http_connect_proxy(self):
        with patch.object(util.my_proxy, "current_proxy_ip", "127.0.0.1:8080"):
            self.assertEqual(
                util._get_proxy(),
                {
                    "http": "http://127.0.0.1:8080",
                    "https": "http://127.0.0.1:8080",
                },
            )


if __name__ == "__main__":
    unittest.main()
