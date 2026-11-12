"""Tests for QTP v1 wire protocol types, PNG encoding, schema, and package metadata."""

from __future__ import annotations

from pathlib import Path
import struct
import unittest
import zlib

import qualia
from qualia import Consequence, Intention, Percept, schema


class TestProtocol(unittest.TestCase):
    def test_percept_default_and_roundtrip(self) -> None:
        frame = Percept(step=3, phase="sample", cue="circle")
        self.assertEqual(frame.width, 64)
        self.assertEqual(frame.height, 48)
        self.assertEqual(len(frame.rgb), 64 * 48 * 3)
        self.assertEqual(frame.pixel(0, 0), (0, 0, 0))

        wire = frame.to_dict()
        self.assertEqual(wire["width"], 64)
        self.assertEqual(wire["height"], 48)
        self.assertEqual(wire["step"], 3)
        self.assertEqual(wire["phase"], "sample")
        self.assertEqual(wire["cue"], "circle")
        self.assertIsInstance(wire["rgb"], str)

        restored = Percept.from_dict(wire)
        self.assertEqual(restored, frame)

    def test_percept_from_rgb_variants_and_validation(self) -> None:
        tuples = [(255, 128, 64), (10, 20, 30), (0, 255, 0), (1, 2, 3)]
        p1 = Percept.from_rgb(tuples, width=2, height=2, step=1)
        self.assertEqual(p1.pixel(0, 0), (255, 128, 64))
        self.assertEqual(p1.pixel(1, 0), (10, 20, 30))
        self.assertEqual(p1.pixel(0, 1), (0, 255, 0))
        self.assertEqual(p1.pixel(1, 1), (1, 2, 3))

        flat = [255, 128, 64, 10, 20, 30, 0, 255, 0, 1, 2, 3]
        p2 = Percept.from_rgb(flat, width=2, height=2, step=1)
        self.assertEqual(p1.rgb, p2.rgb)

        with self.assertRaises(ValueError):
            Percept(width=4, height=4, rgb=b"\x00\x01\x02")

        with self.assertRaises(ValueError):
            Percept(width=0, height=4, rgb=b"")

    def test_percept_png_and_ppm_rendering(self) -> None:
        rgb = bytes([20, 40, 60] * (64 * 48))
        frame = Percept(width=64, height=48, rgb=rgb)

        ppm = frame.to_ppm()
        self.assertTrue(ppm.startswith(b"P6\n64 48\n255\n"))
        self.assertEqual(len(ppm), len(b"P6\n64 48\n255\n") + 64 * 48 * 3)

        png = frame._repr_png_()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        # Read IHDR chunk width and height (default 4x upscale -> 256x192)
        ihdr_len, ihdr_tag = struct.unpack(">I4s", png[8:16])
        self.assertEqual(ihdr_len, 13)
        self.assertEqual(ihdr_tag, b"IHDR")
        width, height, bit_depth, color_type = struct.unpack(">IIBB", png[16:26])
        self.assertEqual(width, 256)
        self.assertEqual(height, 192)
        self.assertEqual(bit_depth, 8)
        self.assertEqual(color_type, 2)

        # Verify IDAT payload decompresses cleanly to 192 scanlines
        idat_len, idat_tag = struct.unpack(">I4s", png[33:41])
        self.assertEqual(idat_tag, b"IDAT")
        compressed = png[41 : 41 + idat_len]
        raw_scanlines = zlib.decompress(compressed)
        self.assertEqual(len(raw_scanlines), 192 * (1 + 256 * 3))

    def test_consequence_serialization(self) -> None:
        outcome = Consequence(
            accepted=False,
            blocked=True,
            completed=True,
            reward=1.25,
            progress=0.125,
            range=0.05,
        )
        self.assertTrue(outcome.success)
        wire = outcome.to_dict()
        self.assertEqual(
            wire,
            {
                "accepted": False,
                "blocked": True,
                "success": True,
                "reward": 1.25,
                "progress": 0.125,
                "range": 0.05,
            },
        )
        restored = Consequence.from_dict(wire)
        self.assertEqual(restored, outcome)

    def test_intention_and_lateral_bias(self) -> None:
        intent = Intention(
            action="right",
            step=7,
            active={"left": 180, "right": 260, "forward": 210},
            candidates={"left": 366, "right": 366, "forward": 366},
            scores={"left": 0.25, "right": 0.75, "forward": 0.50},
            fallback=False,
        )
        self.assertAlmostEqual(intent.bias, 0.5, places=5)

        wire = intent.to_dict()
        restored = Intention.from_dict(wire)
        self.assertEqual(restored, intent)

        # Fallback to active counts when scores are zero
        active_only = Intention(
            action="left",
            step=8,
            active={"left": 300, "right": 100, "forward": 200},
            candidates={"left": 366, "right": 366, "forward": 366},
            scores={"left": 0.0, "right": 0.0, "forward": 0.0},
        )
        self.assertAlmostEqual(active_only.bias, -0.5, places=5)

    def test_qtp_json_schema_and_package_metadata(self) -> None:
        spec = schema()
        self.assertEqual(spec["title"], "Qualia Transmission Protocol (QTP v1)")
        defs = spec["$defs"]
        self.assertIn("Percept", defs)
        self.assertIn("Consequence", defs)
        self.assertIn("Intention", defs)
        self.assertIn("StepRequest", defs)

        repo_root = Path(__file__).resolve().parents[1]
        import json

        pkg_json = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(qualia.__version__, "0.4.0")
        self.assertEqual(pkg_json["version"], qualia.__version__)

        dts_text = (repo_root / "lib/index.d.ts").read_text(encoding="utf-8")
        for symbol in (
            'VERSION = "0.4.0"',
            "export interface PerceptWire",
            "export interface ConsequenceWire",
            "export interface IntentionWire",
            "export interface StepRequest",
            "export declare class Percept",
            "export declare class Consequence",
            "export declare class Intention",
            "export declare class Retina",
            "export declare class LocalEngine",
            "export declare class Client",
            "export declare function connect",
            "export declare function schema",
        ):
            self.assertIn(symbol, dts_text)


if __name__ == "__main__":
    unittest.main()
