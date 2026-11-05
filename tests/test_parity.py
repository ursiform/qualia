"""Compare actual Python and JavaScript behavior over the same trajectories."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import unittest

from qualia import (
    Consequence,
    DEFAULT_URL,
    Intention,
    LocalEngine,
    Percept,
    ProtocolError,
    Retina,
    extract_patches,
    schema,
    openapi,
)


class TestParity(unittest.TestCase):
    def test_python_javascript_frames_flow_history_decisions_and_schema(self):
        root = Path(__file__).resolve().parents[1]
        node = os.environ.get("QUALIA_NODE") or shutil.which("node")
        if not node:
            local = root / ".pixi/envs/default/bin/node"
            if local.exists():
                node = str(local)
        if not node:
            if os.environ.get("CI"):
                self.fail("Node is required for CI parity checks")
            self.skipTest("Node is required for cross-language parity")

        rng = random.Random(314)
        uniform = Percept(rgb=bytes([80] * (64 * 48 * 3)))
        split = Percept(
            rgb=bytes(
                c
                for y in range(48)
                for x in range(64)
                for c in ((255, 0, 0) if x < 21 else (80, 80, 80))
            )
        )
        noise = Percept(rgb=bytes(rng.randrange(256) for _ in range(64 * 48 * 3)))
        retina = Retina()
        frames = [uniform, uniform, split, split, noise, noise]
        frames += [
            retina.observe(d, turn=t, pattern=p)
            for d, t, p in [
                (0.85, "still", "solid"),
                (0.45, "forward", "circle"),
                (0.1, "left", "stripes"),
                (0.3, "right", "solid"),
            ]
        ]
        blocked = Consequence(accepted=False, blocked=True).to_dict()
        completed = Consequence(completed=True, progress=0.1, range=0.2).to_dict()
        cases = {"engines": [], "retinas": [], "wires": []}
        expected = {
            "schema": schema(),
            "url": DEFAULT_URL,
            "openapi": openapi(),
            "engines": [],
            "retinas": [],
            "wires": [],
        }
        for value in (
            0.0000005,
            0.0000015,
            -0.0000005,
            -0.0000015,
            -0.2,
            0.7,
            2**52 - 0.5,
            2**52,
            -(2**52),
            1e303,
            1e308,
            -1e308,
            float.fromhex("0x1.fffffffffffffp+1023"),
        ):
            cases["wires"].append(
                {
                    "kind": "consequence",
                    "value": Consequence(reward=value, progress=value).to_dict()
                    | {"reward": value, "progress": value},
                }
            )
            cases["wires"].append(
                {
                    "kind": "intention",
                    "value": Intention(
                        scores={
                            "left": value,
                            "right": 0.3,
                            "forward": 0.2,
                            "still": 0.1,
                        }
                    ).to_dict()
                    | {
                        "scores": {
                            "left": value,
                            "right": 0.3,
                            "forward": 0.2,
                            "still": 0.1,
                        }
                    },
                }
            )
        bias_cases = json.loads((root / "tests/bias.json").read_text())
        for row in bias_cases:
            cases["wires"].append(
                {
                    "kind": "intention",
                    "value": Intention(
                        scores={
                            "left": row["left"],
                            "right": row["right"],
                            "forward": 0,
                        },
                        active={"left": 2, "right": 8, "forward": 0},
                        candidates={"left": 10, "right": 10, "forward": 10},
                    ).to_dict()
                    | {
                        "scores": {
                            "left": row["left"],
                            "right": row["right"],
                            "forward": 0,
                        }
                    },
                }
            )
        for changes in (
            {"action": "fly"},
            {"action": None},
            {"step": -1},
            {"step": True},
            {"step": 1.5},
            {"fallback": None},
            {"scores": {}},
            {"active": None},
            {"extra": True},
        ):
            cases["wires"].append(
                {"kind": "intention", "value": Intention().to_dict() | changes}
            )
        for kind, Type in (
            ("percept", Percept),
            ("consequence", Consequence),
            ("intention", Intention),
        ):
            for key in Type().to_dict():
                cases["wires"].append(
                    {"kind": kind, "value": Type().to_dict() | {key: None}}
                )
        for row in cases["wires"]:
            try:
                value = {
                    "percept": Percept,
                    "consequence": Consequence,
                    "intention": Intention,
                }[row["kind"]].from_dict(row["value"])
                expected["wires"].append(
                    {
                        "value": value.to_dict(),
                        **({"bias": value.bias} if row["kind"] == "intention" else {}),
                    }
                )
            except ProtocolError:
                expected["wires"].append({"error": True})
        for seed, capacity in [(0, 1), (17, 19), (20261104, 366)]:
            rows = [
                {
                    "frame": frame.to_dict(),
                    "outcome": [None, blocked, completed][i % 3],
                    "action": {2: "left", 5: "forward", 8: "still"}.get(i),
                }
                for i, frame in enumerate(frames)
            ]
            cases["engines"].append(
                {"seed": seed, "candidates": capacity, "rows": rows}
            )
            engine = LocalEngine(seed=seed, candidates_per_pool=capacity)
            prior = None
            results = []
            for row, frame in zip(rows, frames):
                outcome = (
                    Consequence.from_dict(row["outcome"]) if row["outcome"] else None
                )
                patches = extract_patches(frame, prior)
                prior = patches
                intention = None
                if row["action"]:
                    engine.observe(frame, outcome, action=row["action"])
                else:
                    intention = engine.step(frame, outcome).to_dict()
                results.append(
                    {
                        "intention": intention,
                        "status": engine.status(),
                        "patches": [asdict(p) for p in patches],
                    }
                )
            expected["engines"].append(results)

        for width, height, units in [
            (64, 48, "normalized"),
            (31, 17, "physical"),
            (3, 2, "normalized"),
        ]:
            scale = 100 if units == "physical" else 1
            options = {
                "width": width,
                "height": height,
                "units": units,
                "maxDistance": 100,
                "shiftColumns": 4,
                "decay": 0.9,
            }
            rows = [
                {
                    "observe": {
                        "distance": d * scale,
                        "turn": turn,
                        "pattern": pattern,
                        "phase": phase,
                        "cue": "circle",
                    }
                }
                for d, turn, pattern, phase in [
                    (0.9, "still", "solid", "sample"),
                    (0.5, "left", "circle", "choice"),
                    (0.2, "right", "stripes", "visible"),
                    (0.2, 0.125, "solid", "neutral"),
                    (0.2, -0.125, "circle", "visible"),
                    (0.2, 100, "stripes", "visible"),
                    (0.2, -100, "solid", "visible"),
                ]
            ]
            rows += [
                {"blank": {}},
                {"observe": {"distance": 0.005 * scale, "color": [12, 16, 24]}},
                {"reset": True},
                {"observe": {"distance": 0.005 * scale, "step": 12}},
            ]
            cases["retinas"].append({"options": options, "rows": rows})
            retina = Retina(width, height, units=units, max_distance=100)
            results = []
            for row in rows:
                if row.get("reset"):
                    retina.reset()
                elif "blank" in row:
                    results.append(retina.blank(**row["blank"]).to_dict())
                else:
                    results.append(retina.observe(**row["observe"]).to_dict())
            expected["retinas"].append(results)

        process = subprocess.run(
            [node, str(root / "tests/js/parity.mjs")],
            input=json.dumps(cases),
            text=True,
            capture_output=True,
            check=True,
            timeout=20,
        )
        actual = json.loads(process.stdout)
        # Separate comparisons keep a mismatch small enough to diagnose.
        self.assertEqual(actual["schema"], expected["schema"])
        self.assertEqual(actual["url"], expected["url"])
        self.assertEqual(actual["openapi"], expected["openapi"])
        self.assertEqual(actual["wires"], expected["wires"])
        self.assertEqual(len(actual["engines"]), len(expected["engines"]))
        self.assertEqual(len(actual["retinas"]), len(expected["retinas"]))
        for index, (left, right) in enumerate(
            zip(actual["retinas"], expected["retinas"])
        ):
            self.assertEqual(len(left), len(right))
            for step, (a, b) in enumerate(zip(left, right)):
                with self.subTest(retina=index, step=step):
                    self.assertEqual(a, b)
        for index, (left, right) in enumerate(
            zip(actual["engines"], expected["engines"])
        ):
            self.assertEqual(len(left), len(right))
            for step, (a, b) in enumerate(zip(left, right)):
                with self.subTest(engine=index, step=step):
                    self.assertEqual(a, b)
