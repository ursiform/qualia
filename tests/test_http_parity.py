"""Both public clients exercise real HTTP and the same reference policy."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from qualia import Consequence, LocalEngine, Retina, connect
from http_support import running_server, url


class TestHTTPParity(unittest.TestCase):
    def test_python_sync_async_and_javascript_clients_match_over_http(self):
        root = Path(__file__).resolve().parents[1]
        node = os.environ.get("QUALIA_NODE") or shutil.which("node")
        if not node and (root / ".pixi/envs/default/bin/node").exists():
            node = str(root / ".pixi/envs/default/bin/node")
        if not node:
            if os.environ.get("CI"):
                self.fail("Node is required in CI")
            self.skipTest("Node is required for HTTP parity")
        retina = Retina()
        frames = [
            retina.observe(distance, turn=turn, pattern=pattern)
            for distance, turn, pattern in [
                (0.8, "still", "solid"),
                (0.5, "forward", "circle"),
                (0.1, "forward", "stripes"),
                (0.4, "left", "solid"),
                (0.2, "right", "circle"),
                (0.5, "still", "solid"),
            ]
        ]
        outcomes = [
            None,
            Consequence(accepted=False, blocked=True),
            Consequence(),
            Consequence(completed=True, progress=0.1, range=0.2),
            Consequence(accepted=False, blocked=True),
            None,
        ]
        engine = LocalEngine(seed=17)
        expected = [
            engine.step(frame, outcome, fallback=False).to_dict()
            for frame, outcome in zip(frames, outcomes)
        ]
        with running_server(seed=17) as server:
            client = connect(url(server))
            python = []
            for index, (frame, outcome) in enumerate(zip(frames, outcomes)):
                intent = (
                    client.step_sync(frame, outcome)
                    if index % 2 == 0
                    else asyncio.run(client.step(frame, outcome))
                )
                status = client.status_sync()
                status.pop("url")
                python.append({"intention": intent.to_dict(), "status": status})
            self.assertEqual(server.status()["steps"], len(frames))
        cases = [
            {
                "frame": frame.to_dict(),
                "outcome": outcome.to_dict() if outcome else None,
            }
            for frame, outcome in zip(frames, outcomes)
        ]
        with running_server(seed=17) as server:
            process = subprocess.run(
                [node, str(root / "tests/js/http.mjs"), url(server)],
                input=json.dumps(cases),
                text=True,
                capture_output=True,
                check=True,
                timeout=20,
            )
            javascript = json.loads(process.stdout)
            self.assertEqual(server.status()["steps"], len(frames))
        self.assertEqual([row["intention"] for row in python], expected)
        self.assertEqual(javascript, python)
        self.assertTrue(all(row["status"]["policy"] == "reflex" for row in python))
