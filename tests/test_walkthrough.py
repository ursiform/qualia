"""The shipped notebook runs continuously against a real QTP session."""

import ast
from contextlib import redirect_stdout
import inspect
import io
import json
from pathlib import Path
import unittest

from http_support import request, running_server, url


class TestWalkthrough(unittest.IsolatedAsyncioTestCase):
    async def test_local_lite_walkthrough_uses_remote_transport_without_resetting(self):
        notebook = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "lite/content/qualia_walkthrough.ipynb"
            ).read_text()
        )
        origins = ("http://127.0.0.1:8000", "http://localhost:8000")
        with running_server(origins=origins) as server:
            for origin in origins:
                status, headers, _ = request(
                    server,
                    "OPTIONS",
                    "/api/qtp/step",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "content-type",
                    },
                )
                self.assertEqual(status, 204)
                self.assertEqual(headers["Access-Control-Allow-Origin"], origin)
            scope = {}
            configured = False
            with redirect_stdout(io.StringIO()):
                for index, cell in enumerate(notebook["cells"]):
                    if cell["cell_type"] != "code":
                        continue
                    source = "".join(cell["source"]).replace(
                        "    %pip install -q qualia",
                        "    raise AssertionError('Repository package should already be importable')",
                    )
                    code = compile(
                        source,
                        f"walkthrough-cell-{index}",
                        "exec",
                        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
                    )
                    result = eval(code, scope)
                    if inspect.isawaitable(result):
                        await result
                    if not configured and "URL" in scope:
                        self.assertEqual(scope["MODE"], "remote")
                        self.assertEqual(scope["URL"], "http://127.0.0.1:8001")
                        scope["URL"] = url(server)
                        configured = True
            self.assertTrue(configured)
            self.assertEqual(scope["client"].mode, "remote")
            self.assertFalse(scope["intent"].fallback)
            self.assertEqual(scope["client"].step_count, 11)
            self.assertEqual(server.status()["steps"], 11)
            self.assertEqual(len(scope["recorded_frames"]), 10)
            self.assertEqual(scope["recorded_frames"][-1].step, 10)
