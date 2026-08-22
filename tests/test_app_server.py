import json
import stat
import subprocess
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from codex_session_manager.app_server import (
    AppServerClient,
    AppServerError,
    _QueuedResponse,
    parse_preview,
    parse_thread,
)


def text_item(text):
    return {"type": "text", "text": text}


class AppServerParserTests(unittest.TestCase):
    def test_parse_thread_normalizes_summary_and_ignores_unknown_fields(self):
        session = parse_thread(
            {
                "id": "thread-123",
                "preview": "第一条问题",
                "cwd": "/work/project",
                "path": "/tmp/rollout.jsonl",
                "createdAt": 1_700_000_000_000,
                "recencyAt": 1_700_000_100,
                "futureField": {"safe": True},
            }
        )

        self.assertEqual(session.id, "thread-123")
        self.assertEqual(session.first_question, "第一条问题")
        self.assertEqual(session.cwd, "/work/project")
        self.assertEqual(session.rollout_path, "/tmp/rollout.jsonl")
        self.assertEqual(session.created_at, 1_700_000_000.0)
        self.assertEqual(session.last_opened_at, 1_700_000_100.0)

    def test_parse_thread_derives_clean_first_user_question_without_preview(self):
        session = parse_thread(
            {
                "id": "thread-456",
                "preview": "",
                "cwd": "/work/project",
                "path": None,
                "createdAt": 1_700_000_000,
                "updatedAt": 1_700_000_050,
                "turns": [
                    {
                        "items": [
                            {"type": "userMessage", "content": [text_item("<environment_context>hidden</environment_context>")]},
                            {"type": "userMessage", "content": [text_item("真正的问题")]},
                        ]
                    }
                ],
            }
        )

        self.assertEqual(session.first_question, "真正的问题")
        self.assertEqual(session.last_opened_at, 1_700_000_050.0)
        self.assertEqual(session.rollout_path, "")

    def test_parse_thread_rejects_invalid_required_values(self):
        with self.assertRaises(AppServerError):
            parse_thread([])
        with self.assertRaises(AppServerError):
            parse_thread({"id": "missing-fields"})
        with self.assertRaises(AppServerError):
            parse_thread(
                {
                    "id": 123,
                    "preview": "question",
                    "cwd": "/work",
                    "createdAt": 1,
                    "updatedAt": 2,
                }
            )

    def test_parse_preview_extracts_first_and_latest_clean_messages(self):
        preview = parse_preview(
            {
                "thread": {
                    "turns": [
                        {
                            "items": [
                                {"type": "userMessage", "content": [text_item("<environment_context>hidden</environment_context>")]},
                                {"type": "userMessage", "content": [text_item("第一条真实问题")]},
                                {"type": "agentMessage", "text": "第一条回答"},
                            ]
                        },
                        {
                            "items": [
                                {"type": "userMessage", "content": [text_item("最后一个问题")]},
                                {"type": "agentMessage", "text": "最后一个回答"},
                                {"type": "futureMessage", "value": "ignored"},
                            ]
                        },
                    ]
                }
            }
        )

        self.assertEqual(preview.first_question, "第一条真实问题")
        self.assertEqual(preview.latest_user, "最后一个问题")
        self.assertEqual(preview.latest_assistant, "最后一个回答")
        self.assertEqual(preview.error, "")

    def test_parse_preview_rejects_invalid_response_containers(self):
        for value in ([], {}, {"thread": []}, {"thread": {"turns": {}}}):
            with self.subTest(value=value):
                with self.assertRaises(AppServerError):
                    parse_preview(value)

    def test_parse_preview_rejects_malformed_user_content_and_keeps_unknown_types(self):
        def response(content):
            return {
                "thread": {
                    "turns": [
                        {
                            "items": [
                                {"type": "userMessage", "content": content},
                                {"type": "agentMessage", "text": "回答"},
                            ]
                        }
                    ]
                }
            }

        for content in (["not an object"], [{"type": "text", "text": 3}], [{"type": 3}]):
            with self.subTest(content=content):
                with self.assertRaises(AppServerError):
                    parse_preview(response(content))

        preview = parse_preview(
            response([{"type": "futureInput", "value": {"safe": True}}, text_item("真实问题")])
        )
        self.assertEqual(preview.first_question, "真实问题")


class AppServerClientTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.server = self.root / "fake-codex.py"
        self.server.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                import time
                from pathlib import Path

                home = Path(os.environ["CODEX_HOME"])
                log = home / "requests.jsonl"
                late_response = False

                if home.name == "blocked-stdin":
                    time.sleep(1)
                    raise SystemExit(0)

                def record(message):
                    with log.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"message": message, "codex_home": os.environ.get("CODEX_HOME")}) + "\\n")

                def send(message):
                    print(json.dumps(message, ensure_ascii=False), flush=True)

                def thread(identifier, preview, recency):
                    return {
                        "id": identifier,
                        "preview": preview,
                        "cwd": "/work/project",
                        "path": "/tmp/" + identifier + ".jsonl",
                        "createdAt": 1700000000,
                        "updatedAt": recency,
                        "recencyAt": recency,
                    }

                for raw in sys.stdin:
                    message = json.loads(raw)
                    record(message)
                    method = message.get("method")
                    if method == "initialize":
                        if home.name == "initialized-write-failure":
                            os.close(sys.stdin.fileno())
                        send({"method": "thread/started", "params": {"thread": "ignore"}})
                        send({"id": message["id"], "result": {"userAgent": "fake"}})
                        if home.name == "initialized-write-failure":
                            time.sleep(1)
                            raise SystemExit(0)
                    elif method == "thread/list":
                        if home.name == "timeout":
                            time.sleep(5)
                            continue
                        if home.name == "malformed-terminal":
                            sys.stdout.write("{malformed json\\n")
                            sys.stdout.flush()
                            time.sleep(1)
                            continue
                        if home.name == "eof-terminal":
                            raise SystemExit(0)
                        if home.name == "late" and not late_response:
                            late_response = True
                            time.sleep(0.1)
                        if message["params"].get("cursor") is None:
                            result = {"data": [thread("thread-one", "第一条问题", 1700000100)], "nextCursor": "second"}
                        else:
                            result = {"data": [thread("thread-two", "第二条问题", 1700000200)], "nextCursor": None}
                        if home.name == "bad-envelope":
                            send({"id": message["id"], "result": result, "error": {"code": -1, "message": "bad"}})
                        elif home.name == "bad-response-id":
                            send({"id": str(message["id"]), "result": result})
                        elif home.name == "missing-response-id":
                            send({"result": result})
                        elif home.name == "bad-result":
                            send({"id": message["id"], "result": []})
                        elif home.name == "bad-error":
                            send({"id": message["id"], "error": "bad"})
                        else:
                            send({"id": message["id"], "result": result})
                    elif method == "thread/read":
                        if home.name == "error":
                            send({"id": message["id"], "error": {"code": -32000, "message": "read failed"}})
                        else:
                            send({"id": message["id"], "result": {"thread": {"turns": [{"items": [
                                {"type": "userMessage", "content": [{"type": "text", "text": "第一条问题"}]},
                                {"type": "agentMessage", "text": "最后回答"}
                            ]}]}}})
                """
            ),
            encoding="utf-8",
        )
        self.server.chmod(self.server.stat().st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.tempdir.cleanup()

    def make_client(self, home_name="normal", timeout=0.5):
        home = self.root / home_name
        home.mkdir()
        return AppServerClient(self.server, home, "0.1-test", timeout=timeout), home

    @staticmethod
    def requests(home):
        return [
            json.loads(line)
            for line in (home / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        ]

    def test_handshake_pagination_notifications_and_preview(self):
        client, home = self.make_client()
        try:
            sessions = client.list_sessions()
            preview = client.get_preview(sessions[0])
        finally:
            client.close()

        self.assertEqual([session.id for session in sessions], ["thread-two", "thread-one"])
        self.assertEqual(preview.first_question, "第二条问题")
        self.assertEqual(preview.latest_assistant, "最后回答")
        messages = [entry["message"] for entry in self.requests(home)]
        self.assertEqual(
            [message["method"] for message in messages],
            ["initialize", "initialized", "thread/list", "thread/list", "thread/read"],
        )
        self.assertEqual(
            messages[0]["params"],
            {
                "clientInfo": {"name": "codex-session-manager", "version": "0.1-test"},
                "capabilities": {"experimentalApi": False},
            },
        )
        self.assertNotIn("id", messages[1])
        self.assertEqual(
            messages[2]["params"],
            {"sourceKinds": ["cli"], "archived": False, "sortKey": "recency_at", "sortDirection": "desc"},
        )
        self.assertEqual(messages[3]["params"]["cursor"], "second")
        self.assertEqual(messages[4]["params"], {"threadId": "thread-two", "includeTurns": True})
        self.assertTrue(all(entry["codex_home"] == str(home) for entry in self.requests(home)))

    def test_utf8_streams_accept_raw_unicode_json(self):
        calls = []
        real_popen = subprocess.Popen

        def capture_popen(*args, **kwargs):
            calls.append(kwargs)
            return real_popen(*args, **kwargs)

        with patch("codex_session_manager.app_server.subprocess.Popen", side_effect=capture_popen):
            client, _ = self.make_client()
            try:
                sessions = client.list_sessions()
                preview = client.get_preview(sessions[0])
            finally:
                client.close()

        self.assertEqual(sessions[0].first_question, "第二条问题")
        self.assertEqual(preview.latest_assistant, "最后回答")
        self.assertEqual(calls[0]["encoding"], "utf-8")

    def test_json_rpc_errors_are_app_server_errors(self):
        client, _ = self.make_client("error")
        try:
            session = client.list_sessions()[0]
            with self.assertRaisesRegex(AppServerError, "read failed"):
                client.get_preview(session)
        finally:
            client.close()

    def test_rejects_malformed_response_envelopes(self):
        for home_name, expected in (
            ("bad-envelope", "invalid App Server response envelope"),
            ("bad-response-id", "invalid App Server response id"),
            ("missing-response-id", "invalid App Server response id"),
            ("bad-result", "invalid App Server result"),
            ("bad-error", "invalid App Server error"),
        ):
            with self.subTest(home_name=home_name):
                client, _ = self.make_client(home_name)
                try:
                    with self.assertRaisesRegex(AppServerError, expected):
                        client.list_sessions()
                finally:
                    client.close()

    def test_request_timeout_is_an_app_server_error(self):
        client, _ = self.make_client("timeout", timeout=0.05)
        try:
            with self.assertRaisesRegex(AppServerError, "timed out"):
                client.list_sessions()
        finally:
            client.close()

    def test_request_deadline_covers_a_full_unread_stdin_pipe(self):
        home = self.root / "blocked-stdin"
        home.mkdir()
        client = AppServerClient(
            self.server,
            home,
            "x" * (2 * 1024 * 1024),
            timeout=0.05,
        )

        started = time.monotonic()
        try:
            with self.assertRaisesRegex(AppServerError, "timed out"):
                client.list_sessions()
        finally:
            client.close()

        self.assertLess(time.monotonic() - started, 0.5)

    def test_initialize_response_and_notification_share_one_deadline(self):
        client, _ = self.make_client()
        process = Mock()
        process.stdin = Mock()
        process.stdout = Mock()
        process.poll.return_value = None

        with (
            patch("codex_session_manager.app_server.subprocess.Popen", return_value=process),
            patch("codex_session_manager.app_server.os.set_blocking"),
            patch("codex_session_manager.app_server.threading.Thread"),
            patch.object(client, "_send_request", return_value={}) as request,
            patch.object(client, "_send_notification") as notification,
        ):
            client._ensure_started()

        request_deadline = request.call_args.kwargs["deadline"]
        self.assertEqual(request_deadline, notification.call_args.kwargs["deadline"])

    def test_initialized_write_failure_closes_and_reaps_child(self):
        client, _ = self.make_client("initialized-write-failure", timeout=0.1)

        with self.assertRaisesRegex(AppServerError, "could not write"):
            client.list_sessions()

        process = client._process
        self.assertIsNotNone(process)
        for _ in range(20):
            if process.poll() is not None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(process.poll())

    def test_terminal_reader_errors_are_latched_for_reuse(self):
        for home_name, expected in (
            ("malformed-terminal", "malformed App Server JSON"),
            ("eof-terminal", "Codex App Server closed its output"),
        ):
            with self.subTest(home_name=home_name):
                client, home = self.make_client(home_name, timeout=0.1)
                try:
                    with self.assertRaisesRegex(AppServerError, expected) as first:
                        client.list_sessions()
                    started = time.monotonic()
                    with self.assertRaises(AppServerError) as second:
                        client.list_sessions()
                    elapsed = time.monotonic() - started

                    self.assertEqual(str(second.exception), str(first.exception))
                    self.assertLess(elapsed, 0.05)
                    methods = [
                        entry["message"]["method"] for entry in self.requests(home)
                    ]
                    self.assertEqual(methods.count("thread/list"), 1)

                    process = client._process
                    for _ in range(20):
                        if process.poll() is not None:
                            break
                        time.sleep(0.01)
                    self.assertIsNotNone(process.poll())
                finally:
                    client.close()

    def test_late_timeout_response_does_not_poison_the_next_request(self):
        client, _ = self.make_client("late")
        try:
            client._ensure_started()
            client.timeout = 0.05
            with self.assertRaisesRegex(AppServerError, "timed out"):
                client.list_sessions()
            client.timeout = 0.5
            sessions = client.list_sessions()
        finally:
            client.close()

        self.assertEqual([session.id for session in sessions], ["thread-two", "thread-one"])

    def test_response_arriving_after_deadline_times_out_when_already_queued(self):
        client, _ = self.make_client(timeout=0.05)
        client._responses.put(
            _QueuedResponse({"id": 1, "result": {"status": "too late"}}, 100.1)
        )

        with (
            patch.object(client, "_write"),
            patch(
                "codex_session_manager.app_server.time.monotonic",
                side_effect=[100.0, 100.0],
            ),
            self.assertRaisesRegex(AppServerError, "timed out"),
        ):
            client._send_request("thread/list", {})

        self.assertEqual(client._timed_out_ids, set())

    def test_response_arriving_before_deadline_survives_consumer_delay(self):
        client, _ = self.make_client(timeout=0.05)
        client._responses.put(
            _QueuedResponse({"id": 1, "result": {"status": "on time"}}, 100.04)
        )

        with (
            patch.object(client, "_write"),
            patch(
                "codex_session_manager.app_server.time.monotonic",
                side_effect=[100.0, 100.2],
            ),
        ):
            result = client._send_request("thread/list", {})

        self.assertEqual(result, {"status": "on time"})

    def test_close_is_idempotent_and_reaps_child(self):
        client, _ = self.make_client()
        client.list_sessions()
        process = client._process
        stdout = process.stdout

        client.close()
        client.close()

        self.assertIsNotNone(process)
        self.assertIsNotNone(process.poll())
        self.assertTrue(stdout.closed)

    def test_close_returns_while_stubborn_process_is_reaped_later(self):
        client, _ = self.make_client(timeout=0.05)
        release_reaper = threading.Event()
        late_wait_started = threading.Event()
        close_returned = threading.Event()

        class StubbornProcess:
            def __init__(self):
                self.stdin = Mock()
                self.stdout = Mock()
                self.wait_timeouts = []
                self.terminate = Mock()
                self.kill = Mock()

            def poll(self):
                return None

            def wait(self, timeout=None):
                self.wait_timeouts.append(timeout)
                if timeout is not None:
                    raise subprocess.TimeoutExpired("fake-codex", timeout)
                late_wait_started.set()
                release_reaper.wait(1)
                return 0

        process = StubbornProcess()
        client._process = process

        worker = threading.Thread(
            target=lambda: (client.close(), close_returned.set()), daemon=True
        )
        worker.start()
        self.assertTrue(late_wait_started.wait(0.2))
        try:
            self.assertTrue(close_returned.wait(0.2))
        finally:
            release_reaper.set()
            worker.join(1)

        reaper = client._reaper
        self.assertIsNotNone(reaper)
        reaper.join(1)
        self.assertFalse(reaper.is_alive())

        self.assertEqual(process.wait_timeouts[:2], [client.timeout, client.timeout])
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
