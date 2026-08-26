import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from codex_session_manager.cloud_client import (
    CloudClient,
    CloudError,
    SyncConfig,
    default_config_path,
    load_config,
    save_config,
)


class _Handler(BaseHTTPRequestHandler):
    requests = []
    responses = {}
    locations = {}

    def do_GET(self):
        self._respond()

    def do_PUT(self):
        self._respond()

    def do_DELETE(self):
        self._respond()

    def _respond(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).requests.append((self.command, self.path, dict(self.headers), body))
        status, payload = type(self).responses.get((self.command, self.path), (404, {"code": "missing"}))
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        location = type(self).locations.get((self.command, self.path))
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if isinstance(payload, bytes):
            self.wfile.write(payload)
        else:
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        pass


class CloudClientTests(unittest.TestCase):
    def setUp(self):
        _Handler.requests = []
        _Handler.responses = {}
        _Handler.locations = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.client = CloudClient(SyncConfig(f"http://127.0.0.1:{self.server.server_port}/worker/", "secret"))

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_get_index_uses_normalized_url_bearer_header_and_json(self):
        _Handler.responses[("GET", "/worker/api/sessions")] = (200, {"schema_version": 1, "sessions": []})

        self.assertEqual(self.client.get_index(), {"schema_version": 1, "sessions": []})

        method, path, headers, body = _Handler.requests[0]
        self.assertEqual((method, path, body), ("GET", "/worker/api/sessions", b""))
        self.assertEqual(headers["Authorization"], "Bearer secret")

    def test_session_paths_are_urlencoded_and_put_sends_utf8_json(self):
        session_id = "id/with space/中文"
        path = "/worker/api/sessions/id%2Fwith%20space%2F%E4%B8%AD%E6%96%87"
        payload = {"schema_version": 1, "id": session_id, "question": "你好"}
        _Handler.responses[("GET", path)] = (200, payload)
        _Handler.responses[("PUT", path)] = (200, payload)
        _Handler.responses[("DELETE", path)] = (200, {"schema_version": 1, "deleted": True})

        self.assertEqual(self.client.get_session(session_id), payload)
        self.assertEqual(self.client.put_session(payload), payload)
        self.assertEqual(self.client.delete_session(session_id), {"schema_version": 1, "deleted": True})

        put = _Handler.requests[1]
        self.assertEqual(put[0:2], ("PUT", path))
        self.assertEqual(put[2]["Authorization"], "Bearer secret")
        self.assertEqual(put[2]["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(put[3].decode("utf-8")), payload)
        self.assertIn("你好".encode("utf-8"), put[3])

    def test_put_index_and_health(self):
        index = {"schema_version": 1, "sessions": [], "deleted_ids": []}
        _Handler.responses[("PUT", "/worker/api/index")] = (200, index)
        _Handler.responses[("GET", "/worker/health")] = (200, {"ok": True})

        self.assertEqual(self.client.put_index(index), index)
        self.assertEqual(self.client.health(), {"ok": True})
        self.assertEqual(_Handler.requests[1][2]["Authorization"], "Bearer secret")

    def test_unauthorized_and_other_http_errors_are_cloud_errors(self):
        _Handler.responses[("GET", "/worker/api/sessions")] = (401, {"code": "unauthorized"})
        with self.assertRaisesRegex(CloudError, "token"):
            self.client.get_index()

        _Handler.responses[("GET", "/worker/api/sessions")] = (503, {"code": "storage"})
        with self.assertRaisesRegex(CloudError, "HTTP 503"):
            self.client.get_index()

    def test_rejects_malformed_or_unsupported_json(self):
        _Handler.responses[("GET", "/worker/api/sessions")] = (200, b"not json")
        with self.assertRaisesRegex(CloudError, "invalid JSON"):
            self.client.get_index()

        _Handler.responses[("GET", "/worker/api/sessions")] = (200, {"schema_version": 2, "sessions": []})
        with self.assertRaisesRegex(CloudError, "unsupported schema"):
            self.client.get_index()

    def test_rejects_invalid_outgoing_schema_before_request(self):
        with self.assertRaisesRegex(CloudError, "unsupported schema"):
            self.client.put_index({"schema_version": 2, "sessions": []})
        self.assertEqual(_Handler.requests, [])

    def test_rejects_redirect_without_sending_token_to_redirect_target(self):
        redirected_requests = []

        class RedirectTargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                redirected_requests.append(dict(self.headers))
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"schema_version": 1, "sessions": []}')

            def log_message(self, format, *args):
                pass

        target = ThreadingHTTPServer(("127.0.0.1", 0), RedirectTargetHandler)
        target_thread = threading.Thread(target=target.serve_forever)
        target_thread.start()
        self.addCleanup(target.server_close)
        self.addCleanup(target_thread.join)
        self.addCleanup(target.shutdown)
        path = "/worker/api/sessions"
        _Handler.responses[("GET", path)] = (302, {"redirect": True})
        _Handler.locations[("GET", path)] = f"http://127.0.0.1:{target.server_port}/other-host"

        with self.assertRaisesRegex(CloudError, "HTTP 302"):
            self.client.get_index()

        self.assertEqual(len(_Handler.requests), 1)
        self.assertEqual(redirected_requests, [])

    def test_delete_session_rejects_unsupported_schema(self):
        _Handler.responses[("DELETE", "/worker/api/sessions/session")] = (200, {"schema_version": 2, "deleted": True})

        with self.assertRaisesRegex(CloudError, "unsupported schema"):
            self.client.delete_session("session")

    def test_rejects_worker_urls_with_query_or_fragment(self):
        for url in (
            "https://worker.example/?next=elsewhere",
            "https://worker.example/?",
            "https://worker.example/#fragment",
            "https://worker.example/#",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(CloudError, "invalid"):
                    CloudClient(SyncConfig(url, "secret"))

    def test_public_input_errors_are_cloud_errors(self):
        with self.assertRaisesRegex(CloudError, "invalid"):
            CloudClient(SyncConfig("http://[::1", "secret"))

        with self.assertRaisesRegex(CloudError, "ID"):
            self.client.get_session("\ud800")

        client = CloudClient(
            SyncConfig(f"http://127.0.0.1:{self.server.server_port}/worker", "bad\ntoken")
        )
        with self.assertRaisesRegex(CloudError, "request"):
            client.get_index()


class SyncConfigTests(unittest.TestCase):
    def test_default_config_path_uses_xdg_config_location(self):
        self.assertEqual(default_config_path(), Path.home() / ".config" / "codex-session" / "sync.json")

    def test_config_round_trip_is_utf8_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "sync.json"
            config = SyncConfig("https://worker.example/", "秘密")

            save_config(path, config)

            self.assertEqual(load_config(path), config)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"worker_url": config.worker_url, "token": config.token})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_missing_or_malformed_config_is_a_cloud_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sync.json"
            with self.assertRaisesRegex(CloudError, "sync setup"):
                load_config(path)
            path.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(CloudError, "invalid"):
                load_config(path)

    def test_invalid_utf8_config_is_a_cloud_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sync.json"
            path.write_bytes(b"\xff")

            with self.assertRaisesRegex(CloudError, "invalid"):
                load_config(path)

    def test_save_config_mkdir_and_write_failures_are_cloud_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "sync.json"
            config = SyncConfig("https://worker.example/", "secret")

            with mock.patch.object(Path, "mkdir", side_effect=OSError("mkdir failed")):
                with self.assertRaisesRegex(CloudError, "Could not save"):
                    save_config(path, config)
            with mock.patch("codex_session_manager.cloud_client.tempfile.NamedTemporaryFile", side_effect=OSError("write failed")):
                with self.assertRaisesRegex(CloudError, "Could not save"):
                    save_config(path, config)

    def test_save_config_cleanup_failure_preserves_original_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sync.json"
            config = SyncConfig("https://worker.example/", "secret")

            with mock.patch("codex_session_manager.cloud_client.os.replace", side_effect=OSError("replace failed")):
                with mock.patch.object(Path, "unlink", side_effect=OSError("cleanup failed")):
                    with self.assertRaisesRegex(CloudError, "Could not save") as raised:
                        save_config(path, config)

            self.assertEqual(str(raised.exception.__cause__), "replace failed")

    def test_save_config_unicode_write_failure_is_a_cloud_error_without_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "sync.json"

            with self.assertRaisesRegex(CloudError, "Could not save"):
                save_config(path, SyncConfig("https://worker.example/", "\ud800"))

            self.assertEqual(list(path.parent.glob("*.tmp")), [])
