"""A session has one active step, shared across sync, async, and reset."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Event
import unittest
from unittest.mock import patch

from qualia import Intention, Percept, ProtocolError, TransportError, connect


async def overlap_scenario():
    client = connect(mode="auto")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def offline(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        raise TransportError("offline")

    with patch("qualia.client.request_json_async", side_effect=offline):
        first = asyncio.create_task(client.step(Percept()))
        await entered.wait()
        overlap = reset = "accepted"
        try:
            try:
                await client.step(Percept())
            except ProtocolError as error:
                overlap = type(error).__name__
            try:
                client.reset()
            except ProtocolError as error:
                reset = type(error).__name__
        finally:
            release.set()
        intentions = [await first, await client.step(Percept())]
    return {
        "overlap": overlap,
        "reset": reset,
        "calls": calls,
        "steps": [value.step for value in intentions],
        "count": client.step_count,
        "localCount": client.local.step_count,
        "decisions": client.local.status()["decisions"],
    }


class TestSessions(unittest.TestCase):
    def test_python_and_javascript_reject_overlaps_before_capturing_index(self):
        expected = asyncio.run(overlap_scenario())
        self.assertEqual(expected["overlap"], "ProtocolError")
        self.assertEqual(expected["reset"], "ProtocolError")
        self.assertEqual(expected["calls"], 2)
        self.assertEqual(expected["steps"], [0, 1])
        self.assertEqual((expected["count"], expected["localCount"]), (2, 2))
        self.assertEqual(sum(expected["decisions"].values()), 2)
        node = os.environ.get("QUALIA_NODE") or shutil.which("node")
        if not node:
            if os.environ.get("CI"):
                self.fail("Node is required for session parity")
            self.skipTest("Node is required for session parity")
        script = Path(__file__).parent / "js/sessions.mjs"
        result = subprocess.run(
            [node, str(script)], text=True, capture_output=True, check=True, timeout=5
        )
        self.assertEqual(json.loads(result.stdout), expected)

    def test_sync_thread_and_async_calls_share_one_guard(self):
        entered, release = Event(), Event()
        client = connect(mode="auto")

        def offline(*args, **kwargs):
            entered.set()
            release.wait(2)
            raise TransportError("offline")

        with (
            patch("qualia.client.request_json_sync", side_effect=offline),
            patch(
                "qualia.client.request_json_async",
                side_effect=TransportError("offline"),
            ) as asynchronous,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            first = pool.submit(client.step_sync, Percept())
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaises(ProtocolError):
                    client.step_sync(Percept())
                with self.assertRaises(ProtocolError):
                    asyncio.run(client.step(Percept()))
                with self.assertRaises(ProtocolError):
                    client.reset()
                asynchronous.assert_not_called()
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2).step, 0)
            self.assertEqual(client.step_sync(Percept()).step, 1)
        self.assertEqual((client.step_count, client.local.step_count), (2, 2))
        self.assertEqual(sum(client.local.status()["decisions"].values()), 2)

    def test_step_guard_is_released_after_validation_and_transport_failures(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                client = connect()
                target = (
                    "qualia.client.request_json_async"
                    if asynchronous
                    else "qualia.client.request_json_sync"
                )

                def step(frame):
                    return (
                        asyncio.run(client.step(frame))
                        if asynchronous
                        else client.step_sync(frame)
                    )

                with patch(
                    target,
                    side_effect=[
                        TransportError("HTTP 500", status=500),
                        {},
                        Intention(step=0).to_dict(),
                    ],
                ):
                    with self.assertRaises(ProtocolError):
                        step({})
                    for error in (TransportError, ProtocolError):
                        with self.assertRaises(error):
                            step(Percept())
                        self.assertEqual(client.step_count, 0)
                        self.assertEqual(client.local.step_count, 0)
                    self.assertEqual(step(Percept()).step, 0)
                client.reset()
                self.assertEqual(client.step_count, 0)

    def test_cancelled_step_releases_guard_without_advancing_state(self):
        async def run():
            client = connect(mode="auto")
            entered = asyncio.Event()

            async def stalled(*args, **kwargs):
                entered.set()
                await asyncio.Event().wait()

            with patch("qualia.client.request_json_async", side_effect=stalled):
                task = asyncio.create_task(client.step(Percept()))
                await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(client.step_count, 0)
            self.assertEqual(client.local.step_count, 0)
            client.reset()
            with patch(
                "qualia.client.request_json_async",
                side_effect=TransportError("offline"),
            ):
                self.assertEqual((await client.step(Percept())).step, 0)

        asyncio.run(run())
