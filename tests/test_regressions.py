"""Contract and state regressions for embodied sessions."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import urllib.error

from qualia import (
    Consequence,
    Intention,
    Percept,
    ProtocolError,
    Retina,
    TransportError,
    connect,
    extract_patches,
)
from qualia.transport import request_json_async, request_json_sync


def decision(action="left", step=0):
    return Intention(action=action, step=step).to_dict()


READY = {"protocol": "qtp/1.0", "ready": True}


class TestFlowAndRetina(unittest.TestCase):
    def test_static_uniform_and_textured_frames_have_zero_flow(self):
        for rgb in (
            bytes([80] * (64 * 48 * 3)),
            bytes(i % 256 for i in range(64 * 48 * 3)),
        ):
            frame = Percept(rgb=rgb)
            patches = extract_patches(frame, extract_patches(frame))
            self.assertTrue(
                all((p.dx, p.dy, p.drift, p.delta) == (0, 0, 0, 0) for p in patches)
            )

    def test_blank_removes_cue_without_restarting_episode(self):
        retina = Retina()
        retina.observe(0.1, pattern="circle", cue="circle", phase="sample")
        blank = retina.blank()
        self.assertEqual(blank.rgb, bytes([12, 16, 24] * (64 * 48)))
        self.assertEqual((blank.step, blank.phase, blank.cue), (1, "neutral", None))
        next_frame = retina.observe(1, color=(12, 16, 24))
        self.assertEqual(next_frame.rgb, blank.rgb)
        self.assertEqual(next_frame.step, 2)

    def test_annotations_do_not_draw_a_hidden_pattern(self):
        plain = Retina().observe(0.3)
        tagged = Retina().observe(0.3, cue="circle", phase="sample")
        self.assertEqual(plain.rgb, tagged.rgb)
        self.assertNotEqual(plain.rgb, Retina().observe(0.3, pattern="circle").rgb)

    def test_physical_units_do_not_depend_on_reading_history(self):
        retina = Retina(units="physical", max_distance=100)
        first = retina.observe(0.5)
        retina.observe(80)
        retina.reset()
        self.assertEqual(first.rgb, retina.observe(0.5).rgb)
        self.assertEqual(first.rgb, Retina().observe(0.005).rgb)


class TestClientContract(unittest.TestCase):
    def test_bias_matches_extreme_and_threshold_reference_cases(self):
        cases = json.loads((Path(__file__).with_name("bias.json")).read_text())
        for row in cases:
            with self.subTest(left=row["left"], right=row["right"]):
                intention = Intention(
                    scores={"left": row["left"], "right": row["right"], "forward": 0},
                    active={"left": 2, "right": 8, "forward": 0},
                    candidates={"left": 10, "right": 10, "forward": 10},
                )
                self.assertTrue(math.isfinite(intention.bias))
                self.assertEqual(intention.bias, row["bias"])

    def test_large_finite_values_survive_wire_serialization(self):
        for value in (
            2**33,
            2**33 + 0.5,
            100000000000000.5,
            -100000000000000.5,
            2**52,
            -(2**52),
            1e303,
            1e308,
            -1e308,
            sys.float_info.max,
        ):
            consequence = Consequence(reward=value, progress=value, range=abs(value))
            wire = json.loads(json.dumps(consequence.to_dict(), allow_nan=False))
            self.assertEqual(wire["reward"], value)
            self.assertEqual(wire["progress"], value)
            self.assertEqual(wire["range"], abs(value))
            intent = Intention(scores={"left": value, "right": 0.3, "forward": 0.2})
            wire = json.loads(json.dumps(intent.to_dict(), allow_nan=False))
            self.assertEqual(wire["scores"]["left"], value)
            self.assertTrue(math.isfinite(wire["scores"]["left"]))

    def test_default_requires_remote_service(self):
        client = connect()
        self.assertEqual(client.mode, "remote")
        with patch(
            "qualia.client.request_json_sync", side_effect=TransportError("offline")
        ):
            with self.assertRaises(TransportError):
                client.step_sync(Percept())
        self.assertEqual(client.step_count, 0)

    def test_explicit_auto_only_falls_back_on_network_failure(self):
        for failure in (
            TransportError("404", status=404),
            TransportError("403", status=403),
            TransportError("500", status=500),
            TransportError("timeout", timed_out=True),
        ):
            for asynchronous in (False, True):
                client = connect(mode="auto")
                target = (
                    "qualia.client.request_json_async"
                    if asynchronous
                    else "qualia.client.request_json_sync"
                )
                with patch(target, side_effect=failure):
                    with self.assertRaises(TransportError):
                        asyncio.run(
                            client.step(Percept())
                        ) if asynchronous else client.step_sync(Percept())
                self.assertEqual(client.step_count, 0)
                self.assertEqual(client.local.step_count, 0)
        client = connect(mode="auto")
        with patch(
            "qualia.client.request_json_sync", side_effect=TransportError("offline")
        ):
            self.assertTrue(client.step_sync(Percept()).fallback)

    def test_invalid_responses_never_become_decisions(self):
        invalid = [
            {},
            [],
            {"ready": True},
            {"result": decision()},
            {"intention": None},
            {"intention": decision(), "extra": True},
        ]
        changes = [
            {"action": "fly"},
            {"action": None},
            {"step": 999},
            {"step": -1},
            {"step": True},
            {"step": 0.5},
            {"fallback": True},
            {"fallback": "false"},
            {"active": {}},
            {"scores": {"left": float("nan"), "right": 0, "forward": 0}},
            {"candidates": {"left": -1, "right": 0, "forward": 0}},
        ]
        invalid.extend({**decision(), **change} for change in changes)
        invalid.append({**decision(), "active": {"left": 1, "right": 0, "forward": 0}})
        for response in invalid:
            for asynchronous in (False, True):
                with self.subTest(response=response, asynchronous=asynchronous):
                    client = connect(mode="auto")
                    target = (
                        "qualia.client.request_json_async"
                        if asynchronous
                        else "qualia.client.request_json_sync"
                    )
                    with patch(
                        target,
                        side_effect=lambda *args, **kwargs: READY
                        if kwargs.get("method") == "GET"
                        else deepcopy(response),
                    ):
                        with self.assertRaises(ProtocolError):
                            asyncio.run(
                                client.step(Percept())
                            ) if asynchronous else client.step_sync(Percept())
                    self.assertEqual(client.step_count, 0)
                    self.assertIsNone(client.last_action)
                    self.assertEqual(client.local.step_count, 0)

    def test_direct_and_enveloped_intentions(self):
        client = connect()
        with patch(
            "qualia.client.request_json_sync",
            side_effect=[decision(), {"intention": decision("right", 1)}],
        ):
            self.assertEqual(client.step_sync(Percept()).action, "left")
            self.assertEqual(client.step_sync(Percept()).action, "right")
        self.assertEqual(
            client.local.status()["decisions"], {"left": 1, "right": 1, "forward": 0}
        )

    def test_fallback_credits_the_real_remote_action(self):
        for action, expected_streak in (("left", 0), ("forward", 1), ("still", 1)):
            client = connect(mode="auto")
            frame = client.retina.observe(0.4)
            with patch(
                "qualia.client.request_json_sync", side_effect=[READY, decision(action)]
            ):
                client.step_sync(frame)
            self.assertEqual(client.local.status()["last_action"], action)
            with patch(
                "qualia.client.request_json_sync", side_effect=TransportError("offline")
            ):
                intention = client.step_sync(
                    frame, Consequence(accepted=False, blocked=True)
                )
            self.assertEqual(client.local.streak, expected_streak)
            self.assertTrue(intention.fallback)
            self.assertEqual(client.local.step_count, 2)

    def test_status_must_advertise_protocol_and_readiness(self):
        for response in ({"ready": True}, {"protocol": "qtp/1.0", "ready": "true"}):
            with patch("qualia.client.request_json_sync", return_value=response):
                with self.assertRaises(ProtocolError):
                    connect(mode="auto").status_sync()

    def test_wire_values_reject_coercion(self):
        frame = Percept().to_dict()
        for changes in (
            {"width": True},
            {"height": 1.5},
            {"step": -1},
            {"phase": "unknown"},
            {"rgb": "!"},
            {"rgb": None},
        ):
            with self.assertRaises(ProtocolError):
                Percept.from_dict({**frame, **changes})
        for changes in (
            {"accepted": "false"},
            {"range": -1},
            {"reward": float("inf")},
            {"blocked": None},
        ):
            with self.assertRaises(ProtocolError):
                Consequence.from_dict({**Consequence().to_dict(), **changes})


class TestTransport(unittest.TestCase):
    def test_pyodide_strict_utf8_rejects_bad_bytes_without_advancing(self):
        wire = Intention(
            scores={"left": 0, "right": 0, "forward": 0, "extra": 1}
        ).to_dict()
        template = json.dumps(wire).encode()
        invalid = [
            template.replace(b"extra", raw)
            for raw in (
                b"\x80",
                b"\xc3(",
                b"\xed\xa0\x80",
                b"\xf0\x9f",
            )
        ]
        for raw in invalid:
            with self.subTest(raw=raw):

                class Response:
                    status = 200

                    async def bytes(self):
                        return raw

                async def fetch(*args, **kwargs):
                    return Response()

                modules = {
                    "js": types.SimpleNamespace(
                        AbortController=types.SimpleNamespace(
                            new=lambda: types.SimpleNamespace(
                                signal=None, abort=lambda: None
                            )
                        )
                    ),
                    "pyodide": types.ModuleType("pyodide"),
                    "pyodide.http": types.SimpleNamespace(pyfetch=fetch),
                }
                client = connect()
                with patch.dict(sys.modules, modules):
                    with self.assertRaises(ProtocolError):
                        asyncio.run(client.step(Percept()))
                self.assertEqual(client.step_count, 0)
                self.assertEqual(client.local.step_count, 0)

    def test_pyodide_http_errors_abort_unread_bodies(self):
        for status in (403, 404, 503):
            for operation in ("status", "step"):
                with self.subTest(status=status, operation=operation):
                    signal = types.SimpleNamespace(aborted=False)
                    reads = []
                    calls = []
                    response = types.SimpleNamespace(status=status)

                    async def bytes():
                        reads.append(True)
                        await asyncio.Event().wait()

                    response.bytes = bytes

                    async def fetch(url, **options):
                        calls.append(options["method"])
                        self.assertIs(options["signal"], signal)
                        return response

                    controller = types.SimpleNamespace(
                        signal=signal, abort=lambda: setattr(signal, "aborted", True)
                    )
                    modules = {
                        "js": types.SimpleNamespace(
                            AbortController=types.SimpleNamespace(
                                new=lambda: controller
                            )
                        ),
                        "pyodide": types.ModuleType("pyodide"),
                        "pyodide.http": types.SimpleNamespace(pyfetch=fetch),
                    }
                    client = connect()
                    with patch.dict(sys.modules, modules):
                        with self.assertRaises(TransportError) as raised:
                            asyncio.run(
                                client.status()
                                if operation == "status"
                                else client.step(Percept())
                            )
                    self.assertEqual(raised.exception.status, status)
                    self.assertFalse(raised.exception.timed_out)
                    self.assertTrue(signal.aborted)
                    self.assertEqual(reads, [])
                    self.assertEqual(
                        calls, ["GET" if operation == "status" else "POST"]
                    )
                    self.assertEqual(client.step_count, 0)
                    self.assertEqual(client.local.step_count, 0)

    def test_pyodide_failed_post_never_falls_back_or_advances(self):
        for failure in ("headers", "body", "parser"):
            with self.subTest(failure=failure):
                calls = []
                loads = json.loads

                class Response:
                    status = 200

                    def __init__(self, method):
                        self.method = method

                    async def bytes(self):
                        if self.method == "GET":
                            return json.dumps(READY).encode("utf-8")
                        if failure == "body":
                            raise OSError("response body reset")
                        return b"{}"

                async def fetch(url, **options):
                    calls.append(options["method"])
                    if options["method"] == "POST" and failure == "headers":
                        raise OSError("connection lost after remote commit")
                    return Response(options["method"])

                def decode(raw, **options):
                    if raw == "{}" and failure == "parser":
                        raise RecursionError("JSON nesting too deep")
                    return loads(raw, **options)

                modules = {
                    "js": types.SimpleNamespace(
                        AbortController=types.SimpleNamespace(
                            new=lambda: types.SimpleNamespace(
                                signal=None, abort=lambda: None
                            )
                        )
                    ),
                    "pyodide": types.ModuleType("pyodide"),
                    "pyodide.http": types.SimpleNamespace(pyfetch=fetch),
                }
                client = connect(mode="auto")
                with (
                    patch.dict(sys.modules, modules),
                    patch("qualia.transport.json.loads", side_effect=decode),
                ):
                    with self.assertRaises(
                        ProtocolError if failure == "parser" else TransportError
                    ) as raised:
                        asyncio.run(client.step(Percept()))
                self.assertEqual(calls, ["GET", "POST"])
                self.assertEqual(client.step_count, 0)
                self.assertEqual(client.local.step_count, 0)
                self.assertIsNone(client.last_action)
                if failure != "parser":
                    self.assertEqual(
                        raised.exception.status, 200 if failure == "body" else None
                    )

    def test_invalid_json_and_wrong_shapes_are_protocol_failures(self):
        for raw in (b"", b"not-json", b"[]", b"null", b'{"value":NaN}'):

            class Response:
                status = 200

                def read(self):
                    return raw

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

            with patch("urllib.request.OpenerDirector.open", return_value=Response()):
                with self.assertRaises(ProtocolError):
                    request_json_sync("http://example.invalid")

    def test_socket_timeout_is_distinguished_from_connection_refusal(self):
        for error in (TimeoutError(), urllib.error.URLError(TimeoutError())):
            with patch("urllib.request.OpenerDirector.open", side_effect=error):
                with self.assertRaises(TransportError) as raised:
                    request_json_sync("http://example.invalid")
                self.assertTrue(raised.exception.timed_out)

    def test_pyodide_timeout_aborts_headers_and_body(self):
        for stall_body in (False, True):
            controllers = []

            class Controller:
                def __init__(self):
                    self.signal = types.SimpleNamespace(aborted=False)
                    controllers.append(self)

                @classmethod
                def new(cls):
                    return cls()

                def abort(self):
                    self.signal.aborted = True

            class Response:
                status = 200

                async def bytes(self):
                    await asyncio.Event().wait()

            async def fetch(*args, **kwargs):
                if stall_body:
                    return Response()
                await asyncio.Event().wait()

            modules = {
                "js": types.SimpleNamespace(AbortController=Controller),
                "pyodide": types.ModuleType("pyodide"),
                "pyodide.http": types.SimpleNamespace(pyfetch=fetch),
            }
            with patch.dict(sys.modules, modules):
                with self.assertRaises(TransportError) as raised:
                    asyncio.run(
                        request_json_async("http://example.invalid", timeout=0.01)
                    )
            self.assertTrue(raised.exception.timed_out)
            self.assertEqual(raised.exception.status, 200 if stall_body else None)
            self.assertTrue(controllers[0].signal.aborted)

    def test_cancelled_browser_request_is_aborted(self):
        signal = types.SimpleNamespace(aborted=False)
        started = None

        async def fetch(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        controller = types.SimpleNamespace(
            signal=signal, abort=lambda: setattr(signal, "aborted", True)
        )
        modules = {
            "js": types.SimpleNamespace(
                AbortController=types.SimpleNamespace(new=lambda: controller)
            ),
            "pyodide": types.ModuleType("pyodide"),
            "pyodide.http": types.SimpleNamespace(pyfetch=fetch),
        }

        async def run():
            nonlocal started
            started = asyncio.Event()
            task = asyncio.create_task(request_json_async("http://example.invalid"))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        with patch.dict(sys.modules, modules):
            asyncio.run(run())
        self.assertTrue(signal.aborted)
