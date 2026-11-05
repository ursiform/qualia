"""End-to-end tests for QTP Client, LocalEngine reflex loop, and HTTP transport."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import types
from typing import Any
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import qualia
from qualia import Consequence, Retina, TransportError, connect


class _FakeHTTPResponse:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


class TestClient(unittest.TestCase):
    def test_local_engine_loop_and_blocked_streak_recovery(self) -> None:
        client = connect(mode="local")
        retina = Retina()

        f0 = retina.observe(distance=0.4, turn="still")
        i0 = client.step_sync(f0)
        self.assertEqual(i0.action, "forward")
        self.assertTrue(i0.fallback)
        self.assertEqual(i0.step, 0)

        # Report that forward motion was obstructed -> triggers turn recovery
        f1 = retina.observe(distance=0.1, turn="forward")
        blocked_outcome = Consequence(
            accepted=False,
            blocked=True,
            completed=False,
            progress=0.0,
            range=0.1,
        )
        i1 = client.step_sync(f1, blocked_outcome)
        self.assertIn(i1.action, ("left", "right"))
        self.assertEqual(client.local.streak, 1)
        self.assertEqual(i1.step, 1)

        # Once turn succeeds, streak resets to 0
        f2 = retina.observe(distance=0.5, turn=i1.action)
        clear_outcome = Consequence(
            accepted=True,
            blocked=False,
            completed=False,
            progress=0.1,
            range=0.5,
        )
        i2 = client.step_sync(f2, clear_outcome)
        self.assertEqual(client.local.streak, 0)
        self.assertEqual(i2.step, 2)

    def test_remote_and_auto_fallback_against_mock_server(self) -> None:
        requests: list[dict[str, Any]] = []
        server_online = True

        def _fake_urlopen(
            req: urllib.request.Request, timeout: float = 2.0
        ) -> _FakeHTTPResponse:
            if not server_online:
                raise urllib.error.URLError("Connection refused")

            if req.full_url.endswith("/api/status") and req.get_method() == "GET":
                return _FakeHTTPResponse(
                    200, {"protocol": "qtp/1.0", "ready": True, "session": "test-node"}
                )

            if req.full_url.endswith("/api/qtp/step") and req.get_method() == "POST":
                raw = (req.data or b"{}").decode("utf-8")
                body = json.loads(raw)
                requests.append(body)
                step_idx = int(body.get("step", 0))
                consequence = body.get("consequence")
                action = (
                    "left"
                    if (consequence and consequence.get("blocked"))
                    else "forward"
                )
                return _FakeHTTPResponse(
                    200,
                    {
                        "action": action,
                        "step": step_idx,
                        "active": {"left": 250, "right": 210, "forward": 265},
                        "candidates": {"left": 366, "right": 366, "forward": 366},
                        "scores": {
                            "left": 0.68306,
                            "right": 0.57377,
                            "forward": 0.724044,
                        },
                        "fallback": False,
                    },
                )

            raise urllib.error.HTTPError(
                req.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=io.BytesIO(b"{}"),  # type: ignore[arg-type]
            )

        with patch("urllib.request.OpenerDirector.open", side_effect=_fake_urlopen):
            url = "http://127.0.0.1:8001"
            client = connect(url, mode="remote", timeout=2.0)
            status = client.status_sync()
            self.assertEqual(status["engine"], "remote")
            self.assertTrue(status["ready"])

            f0 = client.retina.observe(distance=0.5, turn="still")
            i0 = client.step_sync(f0)
            self.assertEqual(i0.action, "forward")
            self.assertFalse(i0.fallback)
            self.assertAlmostEqual(i0.bias, -0.086956, places=4)

            f1 = client.retina.observe(distance=0.1, turn="forward")
            outcome = Consequence(accepted=False, blocked=True, range=0.1)
            i1 = asyncio.run(client.step(f1, outcome))
            self.assertEqual(i1.action, "left")
            self.assertFalse(i1.fallback)

            self.assertEqual(len(requests), 2)
            req0, req1 = requests
            self.assertEqual(req0["protocol"], "qtp/1.0")
            self.assertIsNone(req0["consequence"])
            self.assertIsNone(req0["action"])
            self.assertEqual(req1["action"], "forward")
            self.assertTrue(req1["consequence"]["blocked"])

            # Take server offline: "remote" raises TransportError, "auto" falls back
            server_online = False
            strict_client = connect(url, mode="remote", timeout=0.2)
            with self.assertRaises(TransportError):
                strict_client.step_sync(f0)

            auto_client = connect(url, mode="auto", timeout=0.2)
            fallback_intent = asyncio.run(auto_client.step(f0))
            self.assertTrue(fallback_intent.fallback)
            self.assertIn(fallback_intent.action, ("left", "right", "forward"))

            fallback_status = auto_client.status_sync()
            self.assertEqual(fallback_status["engine"], "local")
            self.assertTrue(fallback_status["fallback"])

    def test_pyodide_pyfetch_transport_path(self) -> None:
        recorded: dict[str, Any] = {}

        class _FakeResponse:
            status = 200

            async def bytes(self) -> bytes:
                return json.dumps(
                    {
                        "action": "right",
                        "step": 0,
                        "active": {"left": 190, "right": 255, "forward": 200},
                        "candidates": {"left": 366, "right": 366, "forward": 366},
                        "scores": {"left": 0.519, "right": 0.696, "forward": 0.546},
                        "fallback": False,
                    }
                ).encode("utf-8")

        async def _fake_pyfetch(url: str, **kwargs: Any) -> _FakeResponse:
            recorded["url"] = url
            recorded["kwargs"] = kwargs
            return _FakeResponse()

        pyodide_mod = types.ModuleType("pyodide")
        http_mod = types.ModuleType("pyodide.http")
        http_mod.pyfetch = _fake_pyfetch  # type: ignore[attr-defined]
        pyodide_mod.http = http_mod  # type: ignore[attr-defined]

        js_mod = types.ModuleType("js")
        js_mod.AbortController = types.SimpleNamespace(
            new=lambda: types.SimpleNamespace(signal=object(), abort=lambda: None)
        )
        sys.modules["js"] = js_mod
        sys.modules["pyodide"] = pyodide_mod
        sys.modules["pyodide.http"] = http_mod
        try:
            self.assertTrue(qualia.is_pyodide())
            client = connect("http://127.0.0.1:8001", mode="remote")
            frame = client.retina.observe(distance=0.35, turn="still")
            intent = asyncio.run(client.step(frame))
            self.assertEqual(intent.action, "right")
            self.assertFalse(intent.fallback)
            self.assertEqual(recorded["url"], "http://127.0.0.1:8001/api/qtp/step")
            self.assertEqual(recorded["kwargs"]["method"], "POST")
        finally:
            sys.modules.pop("js", None)
            sys.modules.pop("pyodide.http", None)
            sys.modules.pop("pyodide", None)


if __name__ == "__main__":
    unittest.main()
