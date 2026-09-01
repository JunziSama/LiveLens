import json
import threading
import unittest

from websockets.sync.server import serve

from common.onebot_ws import OneBotWebSocketClient


class LocalOneBotServer:
    def __init__(self, handler):
        self.server = serve(handler, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.shutdown()
        self.thread.join(timeout=5)


class OneBotWebSocketClientTest(unittest.TestCase):
    def test_call_sends_auth_and_matches_echo_after_event(self):
        observed = {}

        def handler(connection):
            observed["authorization"] = connection.request.headers.get("Authorization")
            request = json.loads(connection.recv())
            observed["request"] = request
            connection.send(json.dumps({"post_type": "meta_event", "meta_event_type": "heartbeat"}))
            connection.send(
                json.dumps(
                    {
                        "status": "ok",
                        "retcode": 0,
                        "data": {"message_id": 42},
                        "echo": request["echo"],
                    }
                )
            )

        with LocalOneBotServer(handler) as server:
            client = OneBotWebSocketClient(
                f"ws://127.0.0.1:{server.port}/", token="secret", name="test"
            )
            try:
                response = client.call(
                    "send_group_msg",
                    {"group_id": "123", "message": []},
                    timeout=2,
                )
            finally:
                client.close()

        self.assertEqual(observed["authorization"], "Bearer secret")
        self.assertEqual(observed["request"]["action"], "send_group_msg")
        self.assertEqual(response["data"]["message_id"], 42)
        self.assertEqual(response["echo"], observed["request"]["echo"])

    def test_concurrent_calls_receive_their_own_out_of_order_response(self):
        def handler(connection):
            first = json.loads(connection.recv())
            second = json.loads(connection.recv())
            for request in (second, first):
                connection.send(
                    json.dumps(
                        {
                            "status": "ok",
                            "retcode": 0,
                            "data": {"value": request["params"]["value"]},
                            "echo": request["echo"],
                        }
                    )
                )

        with LocalOneBotServer(handler) as server:
            client = OneBotWebSocketClient(f"ws://127.0.0.1:{server.port}/", name="test")
            results = {}

            def invoke(value):
                results[value] = client.call("example", {"value": value}, timeout=2)

            threads = [threading.Thread(target=invoke, args=(value,)) for value in (1, 2)]
            try:
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)
            finally:
                client.close()

        self.assertEqual(results[1]["data"]["value"], 1)
        self.assertEqual(results[2]["data"]["value"], 2)


if __name__ == "__main__":
    unittest.main()
