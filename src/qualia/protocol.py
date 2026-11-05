"""Wire data structures and serialization for the Qualia Transmission Protocol (QTP v1)."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
from pathlib import Path
import struct
from typing import Any, Literal, Mapping, Sequence
import zlib

from .validation import ProtocolError, boolean, fields, integer, number, pools

QTP_VERSION = "qtp/1.0"
DEFAULT_WIDTH = 64
DEFAULT_HEIGHT = 48
MOTOR_ACTIONS: tuple[str, ...] = ("left", "right", "forward")

Action = Literal["left", "right", "forward", "still"]
Phase = Literal["sample", "neutral", "choice", "visible"]
Pattern = Literal["solid", "circle", "stripes"]
Mode = Literal["auto", "remote", "local"]


def schema() -> dict[str, Any]:
    """Return the parsed QTP v1 JSON Schema definition."""
    path = Path(__file__).with_name("qtp.v1.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Percept:
    """A 2D RGB sensory frame transmitted over QTP.

    Attributes:
        width: Frame width in pixels (default 64).
        height: Frame height in pixels (default 48).
        rgb: Row-major uint8 RGB byte buffer of length ``width * height * 3``.
        step: Monotonic step index within the current session.
        phase: Experimental or task phase label (``"sample"``, ``"neutral"``,
            ``"choice"``, or ``"visible"``).
        cue: Optional symbolic cue annotation associated with the frame.
    """

    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    rgb: bytes = field(
        default_factory=lambda: bytes(DEFAULT_WIDTH * DEFAULT_HEIGHT * 3),
        repr=False,
    )
    step: int = 0
    phase: Phase = "visible"
    cue: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "width", integer(self.width, "width", 1))
        object.__setattr__(self, "height", integer(self.height, "height", 1))
        object.__setattr__(self, "step", integer(self.step, "step"))
        if self.phase not in ("sample", "neutral", "choice", "visible"):
            raise ProtocolError("Invalid phase")
        if self.cue is not None and not isinstance(self.cue, str):
            raise ProtocolError("cue must be a string or null")
        expected = self.width * self.height * 3
        if not isinstance(self.rgb, bytes):
            object.__setattr__(self, "rgb", bytes(self.rgb))
        if len(self.rgb) != expected:
            raise ProtocolError(
                f"Percept rgb length must be {expected} bytes for "
                f"{self.width}x{self.height}, got {len(self.rgb)}"
            )

    @classmethod
    def from_rgb(
        cls,
        data: bytes | bytearray | Sequence[int] | Sequence[Sequence[int]],
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        *,
        step: int = 0,
        phase: Phase = "visible",
        cue: str | None = None,
    ) -> Percept:
        """Construct a Percept from raw RGB bytes, flat uint8 ints, or (R, G, B) tuples."""
        if isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        else:
            items = list(data)
            if items and isinstance(items[0], (tuple, list)):
                flat: list[int] = []
                for pixel in items:
                    if len(pixel) != 3:  # type: ignore[arg-type]
                        raise ValueError("Each RGB pixel tuple must contain 3 channels")
                    flat.extend(_clamp_u8(int(c)) for c in pixel)  # type: ignore[union-attr]
                raw = bytes(flat)
            else:
                raw = bytes(_clamp_u8(int(c)) for c in items)  # type: ignore[arg-type]
        return cls(
            width=width,
            height=height,
            rgb=raw,
            step=step,
            phase=phase,
            cue=cue,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Percept:
        """Deserialize a Percept from a QTP JSON dictionary."""
        fields(payload, ("width", "height", "rgb", "step", "phase"), ("cue",))
        if not isinstance(payload["rgb"], str):
            raise ProtocolError("rgb must be a base64 string")
        try:
            rgb = base64.b64decode(payload["rgb"].encode("ascii"), validate=True)
        except (ValueError, UnicodeError) as exc:
            raise ProtocolError("Invalid base64 RGB buffer") from exc
        if base64.b64encode(rgb).decode("ascii") != payload["rgb"]:
            raise ProtocolError("Noncanonical base64 RGB buffer")
        return cls(
            width=payload["width"],
            height=payload["height"],
            rgb=rgb,
            step=payload["step"],
            phase=payload["phase"],
            cue=payload.get("cue"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this Percept to its QTP wire dictionary."""
        return {
            "width": self.width,
            "height": self.height,
            "rgb": base64.b64encode(self.rgb).decode("ascii"),
            "step": self.step,
            "phase": self.phase,
            "cue": self.cue,
        }

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        """Return the (R, G, B) uint8 tuple at pixel coordinates (x, y)."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(
                f"Pixel ({x}, {y}) out of bounds for {self.width}x{self.height}"
            )
        offset = ((y * self.width) + x) * 3
        return (self.rgb[offset], self.rgb[offset + 1], self.rgb[offset + 2])

    def to_ppm(self) -> bytes:
        """Encode the frame as a binary Netpbm P6 PPM image."""
        header = f"P6\n{self.width} {self.height}\n255\n".encode("ascii")
        return header + self.rgb

    def to_png(self, scale: int = 4) -> bytes:
        """Encode the frame as an upscaled RGB PNG using only Python stdlib."""
        if scale < 1:
            raise ValueError("PNG scale factor must be >= 1")
        return _encode_png(self.rgb, self.width, self.height, scale=scale)

    def _repr_png_(self) -> bytes:
        """Render an upscaled crisp pixel-art PNG inline in Jupyter notebooks."""
        return self.to_png(scale=4)


@dataclass(frozen=True)
class Consequence:
    """Embodied one-step outcome of the preceding action.

    Attributes:
        accepted: Whether the physical action transition succeeded.
        blocked: Whether forward motion was obstructed by an obstacle.
        completed: Whether the target or goal state was contacted (serialized
            as ``"success"`` on the wire).
        reward: Optional external scalar reward reading.
        progress: Signed step change toward the target (positive when closing).
        range: Normalized or physical remaining range to the target.
    """

    accepted: bool = True
    blocked: bool = False
    completed: bool = False
    reward: float = 0.0
    progress: float = 0.0
    range: float = 0.0

    def __post_init__(self) -> None:
        for name in ("accepted", "blocked", "completed"):
            boolean(getattr(self, name), name)
        for name in ("reward", "progress"):
            number(getattr(self, name), name)
        number(self.range, "range", 0.0)

    @property
    def success(self) -> bool:
        """Alias for ``completed`` matching the wire field name."""
        return self.completed

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Consequence:
        """Deserialize a Consequence from a QTP JSON dictionary."""
        fields(
            payload, ("accepted", "blocked", "success", "reward", "progress", "range")
        )
        return cls(
            accepted=payload["accepted"],
            blocked=payload["blocked"],
            completed=payload["success"],
            reward=payload["reward"],
            progress=payload["progress"],
            range=payload["range"],
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this Consequence to its QTP wire dictionary."""
        return {
            "accepted": bool(self.accepted),
            "blocked": bool(self.blocked),
            "success": bool(self.completed),
            "reward": _round6(float(self.reward)),
            "progress": _round6(float(self.progress)),
            "range": _round6(float(self.range)),
        }


@dataclass(frozen=True)
class Intention:
    """Discrete motor action decision and candidate pool readout returned by QTP.

    Attributes:
        action: Selected discrete action (``"left"``, ``"right"``, ``"forward"``,
            or ``"still"``).
        step: Step index associated with the decision.
        active: Active unit counts per motor pool.
        candidates: Total candidate pool sizes per motor action.
        scores: Normalized readout scores per motor pool.
        fallback: True when the decision was produced by the local reflex
            fallback driver rather than a remote QTP server.
    """

    action: Action = "still"
    step: int = 0
    active: dict[str, int] = field(
        default_factory=lambda: {"left": 0, "right": 0, "forward": 0}
    )
    candidates: dict[str, int] = field(
        default_factory=lambda: {"left": 0, "right": 0, "forward": 0}
    )
    scores: dict[str, float] = field(
        default_factory=lambda: {"left": 0.0, "right": 0.0, "forward": 0.0}
    )
    fallback: bool = False

    def __post_init__(self) -> None:
        if self.action not in (*MOTOR_ACTIONS, "still"):
            raise ProtocolError("Invalid action")
        object.__setattr__(self, "step", integer(self.step, "step"))
        boolean(self.fallback, "fallback")
        active = pools(self.active, "active", counts=True)
        candidates = pools(self.candidates, "candidates", counts=True)
        pools(self.scores, "scores", counts=False)
        if any(count > candidates.get(key, 0) for key, count in active.items()):
            raise ProtocolError("active counts cannot exceed candidate counts")

    @property
    def bias(self) -> float:
        """Normalized lateral balance in ``[-1.0, +1.0]`` between ``left`` and ``right``.

        Negative values indicate leftward pull, positive values indicate
        rightward pull, and ``0.0`` indicates lateral balance. Useful for
        orienting a secondary communicative axis (such as a robot dome head)
        proportionally to the competing motor pools before moving the drive
        treads.
        """
        left_score = float(self.scores.get("left", 0.0))
        right_score = float(self.scores.get("right", 0.0))
        scale = max(abs(left_score), abs(right_score))
        if scale > 0:
            left, right = left_score / scale, right_score / scale
            total = abs(left) + abs(right)
            # Compare the original magnitude without overflowing its sum.
            if scale > 1e-9 / total:
                return _round6(_clamp((right - left) / total, -1.0, 1.0))

        left_active = float(self.active.get("left", 0))
        right_active = float(self.active.get("right", 0))
        active_sum = left_active + right_active
        if active_sum > 0:
            return _round6(_clamp((right_active - left_active) / active_sum, -1.0, 1.0))
        return 0.0

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Intention:
        """Deserialize an Intention from a QTP JSON dictionary."""
        fields(
            payload, ("action", "step", "active", "candidates", "scores", "fallback")
        )
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this Intention to its QTP wire dictionary."""
        return {
            "action": self.action,
            "step": int(self.step),
            "active": {k: int(v) for k, v in self.active.items()},
            "candidates": {k: int(v) for k, v in self.candidates.items()},
            "scores": {k: _round6(float(v)) for k, v in self.scores.items()},
            "fallback": bool(self.fallback),
        }


def _encode_png(rgb: bytes, width: int, height: int, scale: int = 1) -> bytes:
    """Encode row-major uint8 RGB bytes into a standard PNG image."""
    out_w = width * scale
    out_h = height * scale
    row_stride = width * 3

    scanlines = bytearray()
    for y in range(height):
        row_start = y * row_stride
        if scale == 1:
            row_bytes = rgb[row_start : row_start + row_stride]
        else:
            scaled_row = bytearray(out_w * 3)
            pos = 0
            for x in range(width):
                px = row_start + (x * 3)
                pixel = rgb[px : px + 3]
                for _ in range(scale):
                    scaled_row[pos : pos + 3] = pixel
                    pos += 3
            row_bytes = bytes(scaled_row)
        for _ in range(scale):
            scanlines.append(0)  # PNG filter type 0 (None)
            scanlines.extend(row_bytes)

    ihdr = struct.pack(">IIBBBBB", out_w, out_h, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(scanlines), level=6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _clamp_u8(value: int) -> int:
    if value < 0:
        return 0
    if value > 255:
        return 255
    return value


def _clamp(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _round6(value: float) -> float:
    # Binary64 has no fractional precision at these magnitudes.
    if abs(value) >= 2**52:
        return value
    return round(value * 1_000_000) / 1_000_000
