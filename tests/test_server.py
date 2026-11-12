"""Real HTTP behavior of the loopback reference service."""

from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
from queue import Queue
import signal
import subprocess
import sys
from threading import Thread
import unittest

from qualia import Consequence, TransportError, connect, openapi
from qualia.server import Server
from http_support import initial, request, running_server, url


class TestServer(unittest.TestCase):
    def test_readiness_and_portable_contract_do_not_advance_session(self):
        with running_server(seed=17) as server:
            client = connect(url(server))
            status = client.status_sync()
            self.assertEqual(
                (
                    status["protocol"],
                    status["ready"],
                    status["policy"],
                    status["steps"],
                    status["seed"],
                ),
                ("qtp/1.0", True, "reflex", 0, 17),
            )
            self.assertIsNone(status["last_action"])
            code, headers, contract = request(server, "GET", "/openapi.json")
            self.assertEqual(code, 200)
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertEqual(contract, openapi())
            self.assertEqual(server.status()["steps"], 0)

    def test_ordering_and_preceding_action_conflicts_leave_state_unchanged(self):
        with running_server() as server:
            payload = initial()
            code, _, first = request(server, "POST", "/api/qtp/step", payload)
            self.assertEqual(code, 200)
            self.assertEqual(first["step"], 0)
            self.assertFalse(first["fallback"])
            snapshot = server.status()
            for change in (
                {},
                {"step": 3, "action": first["action"]},
                {"step": 1, "action": "left" if first["action"] != "left" else "right"},
            ):
                code, _, error = request(
                    server, "POST", "/api/qtp/step", {**payload, **change}
                )
                self.assertEqual(code, 409)
                self.assertEqual(error["error"], "sequence")
                self.assertEqual(error["step"], 1)
                self.assertEqual(server.status(), snapshot)
            code, _, second = request(
                server,
                "POST",
                "/api/qtp/step",
                {
                    **payload,
                    "step": 1,
                    "action": first["action"],
                    "consequence": Consequence(accepted=False, blocked=True).to_dict(),
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(second["step"], 1)
            self.assertEqual(server.status()["steps"], 2)

    def test_invalid_messages_do_not_change_engine_history(self):
        changes = [
            {"protocol": "unknown"},
            {"step": True},
            {"step": -1},
            {"step": 0.5},
            {"action": "fly"},
            {"action": "forward"},
            {"consequence": Consequence().to_dict()},
            {"consequence": False},
            {"extra": True},
            {"percept": {}},
            {"percept": {**initial()["percept"], "rgb": "bad!"}},
            {"percept": {**initial()["percept"], "rgb": ""}},
        ]
        with running_server() as server:
            snapshot = server.status()
            for change in changes:
                with self.subTest(change=change):
                    code, _, error = request(
                        server, "POST", "/api/qtp/step", {**initial(), **change}
                    )
                    self.assertEqual(code, 400)
                    self.assertEqual(error["error"], "request")
                    self.assertEqual(server.status(), snapshot)
            for payload in (
                [],
                None,
                b"not-json",
                b"\xff",
                b"[" * 1100 + b"]" * 1100,
                b'{"step":0,"step":1}',
                b'{"step":NaN}',
            ):
                code, _, _ = request(
                    server,
                    "POST",
                    "/api/qtp/step",
                    payload if payload is not None else b"null",
                )
                self.assertEqual(code, 400)
                self.assertEqual(server.status(), snapshot)
            first = initial()
            first.pop("action")
            first.pop("consequence")
            self.assertEqual(request(server, "POST", "/api/qtp/step", first)[0], 200)

    def test_source_frame_index_is_independent_of_decision_index(self):
        with running_server() as server:
            payload = initial()
            payload["percept"]["step"] = 17
            code, _, first = request(server, "POST", "/api/qtp/step", payload)
            self.assertEqual(code, 200)
            code, _, second = request(
                server,
                "POST",
                "/api/qtp/step",
                {**payload, "step": 1, "action": first["action"]},
            )
            self.assertEqual(code, 200)
            self.assertEqual(second["step"], 1)

    def test_two_simultaneous_initial_requests_integrate_only_once(self):
        with running_server() as server:
            with ThreadPoolExecutor(max_workers=2) as executor:
                replies = list(
                    executor.map(
                        lambda _: request(server, "POST", "/api/qtp/step", initial())[
                            0
                        ],
                        range(2),
                    )
                )
            self.assertEqual(sorted(replies), [200, 409])
            self.assertEqual(server.status()["steps"], 1)
            self.assertEqual(sum(server.status()["decisions"].values()), 1)

    def test_another_client_cannot_implicitly_reset_the_session(self):
        with running_server() as server:
            frame = initial()["percept"]
            connect(url(server)).step_sync(frame)
            with self.assertRaises(TransportError) as raised:
                connect(url(server), mode="auto").step_sync(frame)
            self.assertEqual(raised.exception.status, 409)
            self.assertEqual(server.status()["steps"], 1)
        with running_server() as fresh:
            self.assertEqual(connect(url(fresh)).step_sync(frame).step, 0)

    def test_routes_methods_media_and_size_errors(self):
        with running_server() as server:
            for method, path, expected in [
                ("GET", "/missing", 404),
                ("GET", "/api/qtp/step", 405),
                ("POST", "/api/status", 405),
                ("DELETE", "/openapi.json", 405),
            ]:
                code, headers, error = request(server, method, path)
                self.assertEqual(code, expected)
                self.assertIn("error", error)
                if code == 405:
                    self.assertIn("OPTIONS", headers["Allow"])
            self.assertEqual(
                request(
                    server,
                    "POST",
                    "/api/qtp/step",
                    initial(),
                    headers={"Content-Type": "text/plain"},
                )[0],
                415,
            )
            self.assertEqual(
                request(
                    server,
                    "POST",
                    "/api/qtp/step",
                    b"",
                    headers={"Content-Length": str(server.limit + 1)},
                )[0],
                413,
            )
            self.assertEqual(server.status()["steps"], 0)
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=3
            )
            try:
                connection.putrequest("POST", "/api/qtp/step")
                connection.putheader("Content-Type", "application/json")
                connection.endheaders()
                response = connection.getresponse()
                self.assertEqual(response.status, 411)
                self.assertEqual(json.loads(response.read())["error"], "length")
            finally:
                connection.close()

    def test_browser_origin_and_preflight_are_explicit_and_scoped(self):
        origin = "https://notebook.example"
        with running_server(origins=(origin,)) as server:
            headers = {
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type, accept",
                "Access-Control-Request-Private-Network": "true",
            }
            code, response, body = request(
                server, "OPTIONS", "/api/qtp/step", headers=headers
            )
            self.assertEqual((code, body), (204, None))
            self.assertNotIn("Content-Length", response)
            self.assertNotIn("Content-Type", response)
            self.assertEqual(response["Access-Control-Allow-Origin"], origin)
            self.assertEqual(response["Access-Control-Allow-Private-Network"], "true")
            self.assertEqual(response["Vary"], "Origin")
            for change, expected in [
                ({"Origin": "https://untrusted.example"}, 403),
                ({"Origin": "null"}, 403),
                ({"Access-Control-Request-Headers": "Authorization"}, 403),
                ({"Access-Control-Request-Method": "DELETE"}, 405),
            ]:
                self.assertEqual(
                    request(
                        server,
                        "OPTIONS",
                        "/api/qtp/step",
                        headers={**headers, **change},
                    )[0],
                    expected,
                )
            self.assertEqual(request(server, "OPTIONS", "/api/qtp/step")[0], 400)
            self.assertEqual(
                request(
                    server,
                    "POST",
                    "/api/qtp/step",
                    initial(),
                    headers={"Origin": "https://untrusted.example"},
                )[0],
                403,
            )
            self.assertEqual(server.status()["steps"], 0)
            code, response, _ = request(
                server, "POST", "/api/qtp/step", initial(), headers={"Origin": origin}
            )
            self.assertEqual(code, 200)
            self.assertEqual(response["Access-Control-Allow-Origin"], origin)
        with running_server() as server:
            code, headers, _ = request(
                server, "GET", "/api/status", headers={"Origin": origin}
            )
            self.assertEqual(code, 403)
            self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_invalid_configuration_fails_before_binding(self):
        for options in (
            {"seed": -1},
            {"port": -1},
            {"port": 65536},
            {"origins": ("*",)},
            {"origins": ("null",)},
            {"origins": ("https://notebook.example/path",)},
        ):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    Server(**options)

    def test_module_command_starts_and_stops_a_fresh_service(self):
        root = Path(__file__).resolve().parents[1]
        environment = {
            **os.environ,
            "PYTHONPATH": str(root / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "qualia.server",
                "--port",
                "0",
                "--seed",
                "17",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        lines = Queue()
        reader = Thread(
            target=lambda: lines.put(process.stdout.readline()), daemon=True
        )
        reader.start()
        try:
            line = lines.get(timeout=5)
            self.assertIn("policy=reflex seed=17", line)
            address = line.strip().split()[-1]
            self.assertEqual(connect(address).status_sync()["steps"], 0)
            self.assertFalse(connect(address).step_sync(initial()["percept"]).fallback)
        finally:
            if process.poll() is None:
                process.send_signal(
                    signal.SIGINT
                ) if os.name != "nt" else process.terminate()
            _, error = process.communicate(timeout=5)
            reader.join(timeout=5)
        if os.name != "nt":
            self.assertEqual(process.returncode, 0, error)
            self.assertEqual(error, "")
