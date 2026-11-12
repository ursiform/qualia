"""Real HTTP failures must not silently replace committed decisions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import Event, Thread
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from qualia import Intention, Percept, ProtocolError, TransportError, connect
from qualia.transport import request_json_sync


class FailureHandler(BaseHTTPRequestHandler):
    def handle(self):
        self.received = False
        try:
            super().handle()
        finally:
            if not self.received:
                self.server.empty_connection.set()
            self.server.finished.set()

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.received = True
        self.server.gets += 1
        if self.server.mode == "offline":
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        body = json.dumps(
            {
                "protocol": "qtp/1.0",
                "ready": self.server.mode != "unready",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.received = True
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(payload)
        self.server.posts += 1  # The remote step is now committed.
        self.server.posted.set()
        mode = self.server.mode
        if mode == "headers":
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        try:
            if mode == "slow-headers":
                self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Trickle: ")
                self.trickle(b"x" * 300)
                return
            wire = json.dumps(
                Intention(
                    scores={
                        "left": 0,
                        "right": 0,
                        "forward": 0,
                        "extra": 1,
                    }
                ).to_dict()
            ).encode()
            body = {
                "body": b"{",
                "success": wire,
                "json": b"not JSON",
                "utf8": wire.replace(b"extra", b"\xc3("),
                "bom": b"\xef\xbb\xbf" + wire,
                "nested": b'{"x":' * 2000 + b"0" + b"}" * 2000,
                "slow-body": b" " * 300 + b"{}",
                "http": b"{}",
                "http-stream": b" " * 300,
            }[mode]
            self.send_response(503 if mode in ("http", "http-stream") else 200)
            self.send_header(
                "Content-Length", str(100 if mode == "body" else len(body))
            )
            self.end_headers()
            if mode in ("slow-body", "http-stream"):
                self.trickle(body)
            else:
                self.wfile.write(body)
                self.wfile.flush()
                if mode == "body":
                    self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            self.server.disconnected.set()

    def trickle(self, body):
        for byte in body:
            self.wfile.write(bytes([byte]))
            self.wfile.flush()
            sleep(0.01)


@contextmanager
def failure_server(mode):
    with ThreadingHTTPServer(("127.0.0.1", 0), FailureHandler) as server:
        server.mode = mode
        server.gets = server.posts = 0
        server.requests = []
        server.posted = Event()
        server.empty_connection = Event()
        server.disconnected = Event()
        server.finished = Event()
        thread = Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            yield server, f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=2)


def python_failure(url, asynchronous):
    client = connect(url, mode="auto", timeout=0.15)
    try:
        intention = (
            asyncio.run(client.step(Percept()))
            if asynchronous
            else client.step_sync(Percept())
        )
        result = {"action": intention.action, "fallback": intention.fallback}
    except (TransportError, ProtocolError) as error:
        result = {
            "error": type(error).__name__,
            "status": getattr(error, "status", None),
            "timedOut": getattr(error, "timed_out", False),
        }
    return {
        **result,
        "steps": client.step_count,
        "localSteps": client.local.step_count,
        "lastAction": client.last_action,
    }


class TestHTTPFailures(unittest.TestCase):
    def test_cancelled_native_step_cannot_send_after_reset(self):
        for stage in ("dns", "connected"):
            with self.subTest(stage=stage), failure_server("success") as (server, url):
                entered, release = Event(), Event()
                resolve, send = socket.getaddrinfo, http.client.HTTPConnection.send
                notify = None

                def signal_started():
                    entered.set()
                    notify()

                def delayed_resolve(*args, **kwargs):
                    if not entered.is_set():
                        signal_started()
                        release.wait(2)
                    return resolve(*args, **kwargs)

                def delayed_send(connection, data):
                    if not entered.is_set():
                        if connection.sock is None:
                            connection.connect()
                        signal_started()
                        release.wait(2)
                    return send(connection, data)

                async def run():
                    nonlocal notify
                    loop = asyncio.get_running_loop()
                    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
                    started = asyncio.Event()

                    def notify():
                        loop.call_soon_threadsafe(started.set)

                    client = connect(url, timeout=2)
                    task = asyncio.create_task(client.step(Percept(cue="stale")))
                    try:
                        await asyncio.wait_for(started.wait(), 1)
                        task.cancel()
                        start = monotonic()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                        self.assertLess(monotonic() - start, 0.5)
                        self.assertEqual(
                            (client.step_count, client.local.step_count), (0, 0)
                        )
                        client.reset()
                        # The cancelled request must free the only executor
                        # slot while its native DNS call is still paused.
                        fresh = await asyncio.wait_for(
                            client.step(Percept(cue="fresh")), 0.8
                        )
                        self.assertEqual(fresh.step, 0)
                        release.set()
                        self.assertTrue(
                            await asyncio.to_thread(server.empty_connection.wait, 0.8),
                            [row["percept"]["cue"] for row in server.requests],
                        )
                        self.assertEqual(
                            [row["percept"]["cue"] for row in server.requests],
                            ["fresh"],
                        )
                        self.assertEqual(
                            (client.step_count, client.local.step_count), (1, 1)
                        )
                    finally:
                        release.set()
                        if not task.done():
                            task.cancel()
                            try:
                                await task
                            except asyncio.CancelledError:
                                pass

                target = (
                    "socket.getaddrinfo"
                    if stage == "dns"
                    else "http.client.HTTPConnection.send"
                )
                with (
                    patch(target, side_effect=delayed_resolve)
                    if stage == "dns"
                    else patch(target, new=delayed_send)
                ):
                    asyncio.run(run())

    def test_native_cancellation_closes_live_response_sockets(self):
        for mode in ("slow-headers", "slow-body"):
            with self.subTest(mode=mode), failure_server(mode) as (server, url):

                async def run():
                    client = connect(url, timeout=2)
                    task = asyncio.create_task(client.step(Percept()))
                    try:
                        self.assertTrue(await asyncio.to_thread(server.posted.wait, 1))
                        task.cancel()
                        start = monotonic()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                        self.assertLess(monotonic() - start, 0.5)
                        self.assertTrue(
                            await asyncio.to_thread(server.disconnected.wait, 0.8)
                        )
                        self.assertEqual(server.posts, 1)
                        self.assertEqual(
                            (client.step_count, client.local.step_count), (0, 0)
                        )
                        client.reset()
                    finally:
                        if not task.done():
                            task.cancel()
                            try:
                                await task
                            except asyncio.CancelledError:
                                pass

                asyncio.run(run())

    def test_expired_dns_lookup_cannot_send_a_late_request(self):
        release = Event()
        started = Event()
        resolve = socket.getaddrinfo

        def delayed_resolve(*args, **kwargs):
            started.set()
            release.wait(2)
            return resolve(*args, **kwargs)

        with failure_server("offline") as (server, url):
            with patch("socket.getaddrinfo", side_effect=delayed_resolve):
                try:
                    start = monotonic()
                    with self.assertRaises(TransportError) as raised:
                        request_json_sync(url, method="POST", payload={}, timeout=0.15)
                    self.assertLess(monotonic() - start, 0.8)
                    self.assertTrue(started.is_set())
                    self.assertTrue(raised.exception.timed_out)
                finally:
                    release.set()
                self.assertTrue(server.finished.wait(0.8))
            self.assertEqual((server.gets, server.posts), (0, 0))

    def test_native_deadline_closes_trickling_headers_and_body(self):
        for mode in ("slow-headers", "slow-body"):
            for asynchronous in (False, True):
                with self.subTest(mode=mode, asynchronous=asynchronous):
                    with failure_server(mode) as (server, url):
                        start = monotonic()
                        result = python_failure(url, asynchronous)
                        self.assertLess(monotonic() - start, 0.8)
                        self.assertEqual(result["error"], "TransportError")
                        self.assertEqual(
                            result["status"], 200 if mode == "slow-body" else None
                        )
                        self.assertTrue(result["timedOut"])
                        self.assertEqual(result["steps"], 0)
                        self.assertEqual(server.posts, 1)
                        self.assertTrue(server.disconnected.wait(0.8))

    def test_python_and_javascript_failure_classification_and_state_match(self):
        root = Path(__file__).resolve().parents[1]
        node = os.environ.get("QUALIA_NODE") or shutil.which("node")
        if not node and (root / ".pixi/envs/default/bin/node").exists():
            node = str(root / ".pixi/envs/default/bin/node")
        if not node:
            if os.environ.get("CI"):
                self.fail("Node is required for HTTP failure parity")
            self.skipTest("Node is required for HTTP failure parity")
        for mode in (
            "offline",
            "unready",
            "headers",
            "body",
            "http",
            "http-stream",
            "json",
            "utf8",
            "bom",
            "nested",
            "slow-headers",
            "slow-body",
        ):
            rows = []
            for language in ("sync", "async", "javascript"):
                with self.subTest(mode=mode, language=language):
                    with failure_server(mode) as (server, url):
                        if language == "javascript":
                            process = subprocess.run(
                                [node, str(root / "tests/js/failures.mjs"), url],
                                text=True,
                                capture_output=True,
                                check=True,
                                timeout=8,
                            )
                            result = json.loads(process.stdout)
                        else:
                            result = python_failure(url, language == "async")
                        if mode == "http-stream":
                            self.assertTrue(server.disconnected.wait(0.8))
                        rows.append(
                            {**result, "gets": server.gets, "posts": server.posts}
                        )
            with self.subTest(mode=mode):
                self.assertEqual(rows[0], rows[1])
                self.assertEqual(rows[0], rows[2])
                row = rows[0]
                self.assertEqual(row["gets"], 1)
                self.assertEqual(
                    row["posts"], 0 if mode in ("offline", "unready") else 1
                )
                if mode == "offline":
                    self.assertTrue(row["fallback"])
                    self.assertEqual(row["steps"], 1)
                else:
                    self.assertEqual(row["steps"], 0)
                    self.assertEqual(row["localSteps"], 0)
                    self.assertIsNone(row["lastAction"])
                    self.assertEqual(
                        row["error"],
                        "ProtocolError"
                        if mode in ("unready", "json", "utf8", "bom", "nested")
                        else "TransportError",
                    )
                    self.assertEqual(row["timedOut"], mode.startswith("slow-"))
                    self.assertEqual(
                        row["status"],
                        200
                        if mode in ("body", "slow-body")
                        else 503
                        if mode in ("http", "http-stream")
                        else None,
                    )
