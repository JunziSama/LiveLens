import unittest
from unittest.mock import Mock, patch

from query_task.query_bilibili import QueryBilibili


class QueryBilibiliReliabilityTest(unittest.TestCase):
    @staticmethod
    def make_task(**overrides):
        config = {
            "name": "bilibili-test",
            "enable": True,
            "type": "bilibili",
            "uid_list": [2],
            "cookie": "",
            "payload": "",
            "enable_dynamic_check": True,
            "enable_living_check": True,
        }
        config.update(overrides)
        return QueryBilibili(config)

    def test_empty_payload_skips_buvid_activation(self):
        task = self.make_task(payload="")
        with (
            patch.object(task, "generate_buvid3", return_value="generated-buvid"),
            patch("query_task.query_bilibili.util.requests_post") as request,
        ):
            result = task.get_new_buvid3()

        self.assertEqual(result, "generated-buvid")
        request.assert_not_called()

    def test_none_buvid_is_not_cached(self):
        task = self.make_task()
        with (
            patch("query_task.query_bilibili.get_cached_value", return_value=None),
            patch.object(task, "get_new_buvid3", return_value=None),
            patch("query_task.query_bilibili.set_cached_value") as set_cache,
        ):
            task.init_buvid3()

        self.assertIsNone(task.buvid3)
        set_cache.assert_not_called()

    def test_412_and_non_json_responses_are_rejected(self):
        task = self.make_task()
        blocked = Mock(status_code=412, headers={"Content-Type": "text/html"})
        html = Mock(status_code=200, headers={"Content-Type": "text/html"})

        self.assertIsNone(task._response_json(blocked, "测试"))
        self.assertIsNone(task._response_json(html, "测试"))
        blocked.json.assert_not_called()
        html.json.assert_not_called()

    def test_live_status_uses_retryable_json_request(self):
        task = self.make_task()
        response = Mock(
            status_code=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        response.json.return_value = {"code": 0, "data": {}}

        with patch(
            "query_task.query_bilibili.util.requests_post",
            return_value=response,
        ) as request:
            task.query_live_status_batch([2])

        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["json"], {"uids": [2]})
        self.assertTrue(kwargs["retryable"])
        self.assertIs(kwargs["session"], task.session)

    def test_live_status_failure_does_not_raise_or_change_state(self):
        task = self.make_task()
        with patch(
            "query_task.query_bilibili.util.requests_post",
            return_value=None,
        ):
            task.query_live_status_batch([2])

        self.assertEqual(task.living_status_dict, {})


if __name__ == "__main__":
    unittest.main()
