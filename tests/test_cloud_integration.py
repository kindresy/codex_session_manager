import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from codex_session_manager.cloud_client import CloudClient, SyncConfig
from codex_session_manager.cloud_repository import (
    CloudPreviewService,
    CloudSessionRepository,
)
from codex_session_manager.models import Session
from codex_session_manager.sync import SyncResult, sync_sessions


SESSION_ID = "synthetic/session-\u4e00"


class _WorkerHandler(BaseHTTPRequestHandler):
    index = {}
    sessions = {}
    requests = []

    def do_GET(self):
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        type(self).requests.append((self.command, self.path))
        if self.path == "/api/sessions":
            return self._json(200, type(self).index)
        session_id = self._session_id()
        if session_id in type(self).sessions:
            return self._json(200, type(self).sessions[session_id])
        return self._json(404, {"error": "not_found"})

    def do_PUT(self):
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        type(self).requests.append((self.command, self.path))
        payload = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        )
        if self.path == "/api/index":
            type(self).index = payload
        else:
            type(self).sessions[self._session_id()] = payload
        return self._json(200, payload)

    def do_DELETE(self):
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        type(self).requests.append((self.command, self.path))
        session_id = self._session_id()
        type(self).sessions.pop(session_id, None)
        type(self).index["sessions"] = [
            entry for entry in type(self).index["sessions"] if entry["id"] != session_id
        ]
        if session_id not in type(self).index["deleted_ids"]:
            type(self).index["deleted_ids"].append(session_id)
        return self._json(200, {"schema_version": 1, "deleted": True})

    def _authorized(self):
        return self.headers.get("Authorization") == "Bearer integration-token"

    def _session_id(self):
        prefix = "/api/sessions/"
        return unquote(self.path.removeprefix(prefix)) if self.path.startswith(prefix) else ""

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class _SyntheticAppServer:
    def list_sessions(self):
        return [Session(SESSION_ID, "synthetic question", "/synthetic/work", 10, 20, "")]

    def read_thread(self, session_id):
        if session_id != SESSION_ID:
            raise AssertionError("unexpected synthetic session")
        return {
            "thread": {
                "turns": [
                    {
                        "items": [
                            {"type": "userMessage", "content": [{"type": "text", "text": "synthetic question"}]},
                            {"type": "agentMessage", "text": "synthetic answer"},
                            {
                                "type": "commandExecution",
                                "command": "synthetic-command",
                                "cwd": "/synthetic/work",
                                "status": "completed",
                                "aggregatedOutput": "synthetic output",
                                "exitCode": 0,
                            },
                        ]
                    }
                ]
            }
        }


class CloudIntegrationTests(unittest.TestCase):
    def setUp(self):
        _WorkerHandler.index = {
            "schema_version": 1,
            "generated_at": None,
            "sessions": [],
            "deleted_ids": [],
        }
        _WorkerHandler.sessions = {}
        _WorkerHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _WorkerHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.client = CloudClient(
            SyncConfig(
                f"http://127.0.0.1:{self.server.server_port}",
                "integration-token",
            )
        )

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_upload_list_read_and_delete_with_synthetic_data(self):
        result = sync_sessions(_SyntheticAppServer(), self.client)
        sessions = CloudSessionRepository(self.client).list_sessions()
        preview = CloudPreviewService(self.client).get(sessions[0])
        deleted = self.client.delete_session(SESSION_ID)

        self.assertEqual(result, SyncResult(uploaded=1, skipped=0, failed=()))
        self.assertEqual([session.id for session in sessions], [SESSION_ID])
        self.assertEqual(preview.latest_assistant, "synthetic answer")
        self.assertEqual(deleted, {"schema_version": 1, "deleted": True})
        self.assertEqual(_WorkerHandler.sessions, {})
        self.assertEqual(_WorkerHandler.index["sessions"], [])
        self.assertEqual(_WorkerHandler.index["deleted_ids"], [SESSION_ID])
        self.assertEqual(
            _WorkerHandler.requests,
            [
                ("GET", "/api/sessions"),
                ("PUT", "/api/sessions/synthetic%2Fsession-%E4%B8%80"),
                ("PUT", "/api/index"),
                ("GET", "/api/sessions"),
                ("GET", "/api/sessions/synthetic%2Fsession-%E4%B8%80"),
                ("DELETE", "/api/sessions/synthetic%2Fsession-%E4%B8%80"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
