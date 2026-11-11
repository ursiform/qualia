"""Egocentric 1D-to-2D sensory projection and retinal patch flow helpers."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from .validation import ProtocolError, integer, number

from .protocol import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    Pattern,
    Percept,
    Phase,
)

PATCH_GRID_WIDTH = 16
PATCH_GRID_HEIGHT = 16
LUMA_RED = 0.2126
LUMA_GREEN = 0.7152
LUMA_BLUE = 0.0722


@dataclass(frozen=True)
class PatchFlow:
    """Optical flow and luminance statistics for one retinal patch."""

    x: int
    y: int
    red: float
    green: float
    blue: float
    power: float
    contrast: float
    delta: float = 0.0
    rise: float = 0.0
    fall: float = 0.0
    dx: int = 0
    dy: int = 0
    drift: float = 0.0


class Retina:
    """Synthesizes 2D RGB Percept frames from 1D range/color readings and ego-motion.

    Physical differential-drive robots often carry a single forward-facing
    distance and color sensor rather than a 2D camera. ``Retina`` maintains an
    egocentric visual buffer across ``width x height`` pixels so that:

    1. Turning ``"left"`` shifts existing visual columns **rightward** across
       the field of view before painting the new foveal reading (generating
       rightward lateral optical flow).
    2. Turning ``"right"`` shifts existing visual columns **leftward** across
       the field of view (generating leftward lateral optical flow).
    3. Approaching an object (decreasing ``distance``) expands the central
       foveal projection vertically and increases its luminance (generating
       looming optical flow ``rise`` and ``power``).
    """

    def __init__(
        self,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        *,
        ambient: tuple[int, int, int] = (12, 16, 24),
        shift_columns: int = 4,
        decay: float = 0.90,
        max_distance: float = 100.0,
        units: Literal["normalized", "physical"] = "normalized",
    ) -> None:
        width = integer(width, "width", 1)
        height = integer(height, "height", 1)
        integer(shift_columns, "shift_columns", 1)
        number(max_distance, "max_distance", 0.0)
        if max_distance == 0 or units not in ("normalized", "physical"):
            raise ProtocolError(
                "Choose positive max_distance and explicit distance units"
            )
        number(decay, "decay", 0.0)
        if decay > 1.0:
            raise ProtocolError("decay must be <= 1")
        self.width = width
        self.height = height
        self.ambient: tuple[int, int, int] = (
            _clamp_u8(ambient[0]),
            _clamp_u8(ambient[1]),
            _clamp_u8(ambient[2]),
        )
        self.shift_columns = max(1, int(shift_columns))
        self.decay = max(0.0, min(1.0, float(decay)))
        self.max_distance = float(max_distance)
        self.units = units
        self._step = 0
        self._buffer = self._blank_buffer(self.ambient)

    @property
    def step(self) -> int:
        """Number of frames observed since initialization or reset."""
        return self._step

    def reset(self, ambient: tuple[int, int, int] | None = None) -> None:
        """Clear the retinal buffer back to the ambient background."""
        if ambient is not None:
            self.ambient = (
                _clamp_u8(ambient[0]),
                _clamp_u8(ambient[1]),
                _clamp_u8(ambient[2]),
            )
        self._step = 0
        self._buffer = self._blank_buffer(self.ambient)

    def observe(
        self,
        distance: float,
        color: tuple[int, int, int] = (220, 220, 255),
        turn: str | float = "still",
        ambient: tuple[int, int, int] | None = None,
        *,
        pattern: Pattern | None = None,
        phase: Phase = "visible",
        cue: str | None = None,
        step: int | None = None,
    ) -> Percept:
        """Project a forward range/color sample and ego-turn into a 2D Percept.

        Args:
            distance: Forward range in the constructor's declared units.
                Normalized range uses 0 for contact and 1 for the horizon.
                Physical range is divided by ``max_distance``.
            color: Base ``(R, G, B)`` color tuple of the detected surface.
            turn: Ego-motion since the previous frame: ``"left"``, ``"right"``,
                ``"forward"``, ``"still"``, or a signed angular/column float
                (negative = left turn, positive = right turn).
            ambient: Optional override for the background ``(R, G, B)`` tuple.
            pattern: Explicit surface pattern; defaults to ``"solid"``.
                The cue annotation never changes pixels.
            phase: QTP phase label for the emitted Percept.
            cue: Optional symbolic cue annotation for the emitted Percept.
            step: Optional explicit step number (defaults to internal counter).
        """
        bg = (
            (_clamp_u8(ambient[0]), _clamp_u8(ambient[1]), _clamp_u8(ambient[2]))
            if ambient is not None
            else self.ambient
        )
        dx = self._turn_shift(turn)
        self._shift_and_decay(dx, bg)

        norm_dist = self._normalize_distance(distance)
        proximity = 1.0 - norm_dist

        active_pattern: Pattern = "solid"
        if pattern in ("solid", "circle", "stripes"):
            active_pattern = pattern

        self._paint_fovea(
            proximity=proximity,
            color=(_clamp_u8(color[0]), _clamp_u8(color[1]), _clamp_u8(color[2])),
            ambient=bg,
            pattern=active_pattern,
        )

        frame_step = self._step if step is None else integer(step, "step")
        self._step = frame_step + 1
        return Percept(
            width=self.width,
            height=self.height,
            rgb=bytes(self._buffer),
            step=frame_step,
            phase=phase,
            cue=cue,
        )

    def blank(self, *, phase: Phase = "neutral", step: int | None = None) -> Percept:
        """Clear retained sensory traces and emit an ambient-only frame.

        Use this at cue removal when the apparatus must retain no visual cue.
        The frame counter continues; episode reset is a separate operation.
        """
        frame_step = self._step if step is None else integer(step, "step")
        frame = Percept(
            width=self.width,
            height=self.height,
            rgb=bytes(self._blank_buffer(self.ambient)),
            step=frame_step,
            phase=phase,
        )
        self._buffer = bytearray(frame.rgb)
        self._step = frame_step + 1
        return frame

    def _normalize_distance(self, distance: float) -> float:
        number(distance, "distance", 0.0)
        scale = self.max_distance if self.units == "physical" else 1.0
        return min(1.0, float(distance) / scale)

    def _turn_shift(self, turn: str | float) -> int:
        """Compute pixel column shift across the retina for an ego-turn.

        Turning left rotates the sensor counterclockwise, so previously seen
        world features shift rightward (+x) across the retinal sheet. Turning
        right shifts previously seen world features leftward (-x).
        """
        if isinstance(turn, (int, float)):
            number(turn, "turn")
            if abs(float(turn)) < 1e-6:
                return 0
            # Negative angle = left turn -> rightward optical shift (+x)
            # Positive angle = right turn -> leftward optical shift (-x)
            scaled = int(round(-float(turn) * self.shift_columns))
            if scaled == 0:
                return self.shift_columns if turn < 0 else -self.shift_columns
            return max(-self.width // 2, min(self.width // 2, scaled))

        label = str(turn).strip().lower()
        if label == "left":
            return self.shift_columns
        if label == "right":
            return -self.shift_columns
        return 0

    def _shift_and_decay(self, dx: int, ambient: tuple[int, int, int]) -> None:
        w = self.width
        h = self.height
        old = self._buffer
        new = self._blank_buffer(ambient)
        decay = self.decay
        ar, ag, ab = ambient

        for y in range(h):
            row_offset = y * w * 3
            for x in range(w):
                src_x = x - dx
                if 0 <= src_x < w:
                    src_idx = row_offset + (src_x * 3)
                    dst_idx = row_offset + (x * 3)
                    r = old[src_idx]
                    g = old[src_idx + 1]
                    b = old[src_idx + 2]
                    new[dst_idx] = _clamp_u8(int(round(ar + (r - ar) * decay)))
                    new[dst_idx + 1] = _clamp_u8(int(round(ag + (g - ag) * decay)))
                    new[dst_idx + 2] = _clamp_u8(int(round(ab + (b - ab) * decay)))
        self._buffer = new

    def _paint_fovea(
        self,
        *,
        proximity: float,
        color: tuple[int, int, int],
        ambient: tuple[int, int, int],
        pattern: Pattern,
    ) -> None:
        w = self.width
        h = self.height
        cx = w // 2
        cy = h // 2

        # Foveal bar spans 2 central patch columns (8 px on a 64-wide retina)
        # so lateral shifts of 4 px move prior energy cleanly into adjacent patches.
        fovea_half_w = max(2, w // 16)
        x0 = max(0, cx - fovea_half_w)
        x1 = min(w, cx + fovea_half_w)

        min_h = max(4, h // 12)
        max_h = max(min_h + 2, h - 4)
        bar_h = int(round(min_h + proximity * (max_h - min_h)))
        half_h = max(2, bar_h // 2)
        y0 = max(0, cy - half_h)
        y1 = min(h, cy + half_h)

        # Brightness scales with proximity so forward approach increases patch power.
        gain = 0.25 + (0.75 * proximity)
        ar, ag, ab = ambient
        cr, cg, cb = color

        buf = self._buffer
        radius_x = max(1.0, float(x1 - x0) / 2.0)
        radius_y = max(1.0, float(y1 - y0) / 2.0)
        mid_x = (x0 + x1 - 1) / 2.0
        mid_y = (y0 + y1 - 1) / 2.0

        for y in range(y0, y1):
            for x in range(x0, x1):
                norm_x = (x - mid_x) / radius_x
                norm_y = (y - mid_y) / radius_y

                if pattern == "circle":
                    dist_sq = (norm_x * norm_x) + (norm_y * norm_y)
                    if dist_sq > 1.05:
                        continue
                    ring = 0.75 + 0.25 * math.cos(math.sqrt(dist_sq) * math.pi)
                    shade = gain * ring
                elif pattern == "stripes":
                    stripe = 1.0 if ((x + y) // 2) % 2 == 0 else 0.35
                    shade = gain * stripe
                else:
                    # Subtle edge relief so patches carry both power and contrast
                    edge_boost = 1.0 - 0.18 * (abs(norm_x) + 0.5 * abs(norm_y))
                    shade = gain * max(0.4, edge_boost)

                idx = ((y * w) + x) * 3
                buf[idx] = _clamp_u8(int(round(ar + (cr - ar) * shade)))
                buf[idx + 1] = _clamp_u8(int(round(ag + (cg - ag) * shade)))
                buf[idx + 2] = _clamp_u8(int(round(ab + (cb - ab) * shade)))

    def _blank_buffer(self, ambient: tuple[int, int, int]) -> bytearray:
        ar, ag, ab = ambient
        return bytearray([ar, ag, ab] * (self.width * self.height))


def extract_patches(
    percept: Percept,
    previous: list[PatchFlow] | None = None,
    *,
    grid_width: int = PATCH_GRID_WIDTH,
    grid_height: int = PATCH_GRID_HEIGHT,
) -> list[PatchFlow]:
    """Slice a Percept into a grid of patches with luminance and optical flow cues."""
    w = percept.width
    h = percept.height
    rgb = percept.rgb

    base_patches: list[PatchFlow] = []
    for py in range(grid_height):
        y0 = (py * h) // grid_height
        y1 = max(y0, (((py + 1) * h) // grid_height) - 1)
        for px in range(grid_width):
            x0 = (px * w) // grid_width
            x1 = max(x0, (((px + 1) * w) // grid_width) - 1)
            red, green, blue, power, contrast = _patch_stats(rgb, w, x0, x1, y0, y1)
            base_patches.append(
                PatchFlow(
                    x=px,
                    y=py,
                    red=red,
                    green=green,
                    blue=blue,
                    power=power,
                    contrast=contrast,
                )
            )

    if not previous:
        return base_patches

    prev_index: dict[tuple[int, int], PatchFlow] = {(p.x, p.y): p for p in previous}
    with_flow: list[PatchFlow] = []
    for patch in base_patches:
        prior = prev_index.get((patch.x, patch.y))
        if prior is None:
            delta = 0.0
            rise = 0.0
            fall = 0.0
        else:
            delta = _round6(patch.power - prior.power)
            rise = _round6(max(0.0, min(1.0, delta)))
            fall = _round6(max(0.0, min(1.0, -delta)))

        dx, dy, drift = _patch_drift(
            patch, prev_index, grid_width=grid_width, grid_height=grid_height
        )
        with_flow.append(
            PatchFlow(
                x=patch.x,
                y=patch.y,
                red=patch.red,
                green=patch.green,
                blue=patch.blue,
                power=patch.power,
                contrast=patch.contrast,
                delta=delta,
                rise=rise,
                fall=fall,
                dx=dx,
                dy=dy,
                drift=drift,
            )
        )
    return with_flow


def center_of_mass_x(
    percept: Percept, ambient: tuple[int, int, int] = (12, 16, 24)
) -> float:
    """Compute the horizontal luminance center of mass above ambient in [0, width - 1]."""
    w = percept.width
    h = percept.height
    rgb = percept.rgb
    base_luma = (
        LUMA_RED * ambient[0] + LUMA_GREEN * ambient[1] + LUMA_BLUE * ambient[2]
    ) / 255.0

    weighted_x = 0.0
    total_weight = 0.0
    for y in range(h):
        row_offset = y * w * 3
        for x in range(w):
            idx = row_offset + (x * 3)
            luma = (
                LUMA_RED * rgb[idx]
                + LUMA_GREEN * rgb[idx + 1]
                + LUMA_BLUE * rgb[idx + 2]
            ) / 255.0
            excess = max(0.0, luma - base_luma)
            weighted_x += x * excess
            total_weight += excess

    if total_weight <= 1e-9:
        return (w - 1) / 2.0
    return weighted_x / total_weight


def _patch_stats(
    rgb: bytes, width: int, x0: int, x1: int, y0: int, y1: int
) -> tuple[float, float, float, float, float]:
    count = 0
    r_sum = 0
    g_sum = 0
    b_sum = 0
    lumas: list[float] = []

    for y in range(y0, y1 + 1):
        row_offset = y * width * 3
        for x in range(x0, x1 + 1):
            idx = row_offset + (x * 3)
            r = rgb[idx]
            g = rgb[idx + 1]
            b = rgb[idx + 2]
            r_sum += r
            g_sum += g
            b_sum += b
            lumas.append((LUMA_RED * r + LUMA_GREEN * g + LUMA_BLUE * b) / 255.0)
            count += 1

    if count == 0:
        return (0.0, 0.0, 0.0, 0.0, 0.0)

    red = r_sum / count / 255.0
    green = g_sum / count / 255.0
    blue = b_sum / count / 255.0
    power = math.sqrt(((red * red) + (green * green) + (blue * blue)) / 3.0)
    mean_luma = sum(lumas) / count
    variance = sum((v - mean_luma) ** 2 for v in lumas) / count
    contrast = math.sqrt(variance)
    return (
        _round6(red),
        _round6(green),
        _round6(blue),
        _round6(power),
        _round6(contrast),
    )


def _patch_drift(
    patch: PatchFlow,
    prev_index: dict[tuple[int, int], PatchFlow],
    *,
    grid_width: int,
    grid_height: int,
) -> tuple[int, int, float]:
    candidates: list[PatchFlow] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx = patch.x + dx
            ny = patch.y + dy
            if 0 <= nx < grid_width and 0 <= ny < grid_height:
                prior = prev_index.get((nx, ny))
                if prior is not None:
                    candidates.append(prior)

    if not candidates:
        return (0, 0, 0.0)

    best = candidates[0]
    best_dist = _feature_distance(patch, best)
    for candidate in candidates[1:]:
        dist = _feature_distance(patch, candidate)
        displacement = abs(patch.x - candidate.x) + abs(patch.y - candidate.y)
        best_displacement = abs(patch.x - best.x) + abs(patch.y - best.y)
        if dist < best_dist or (dist == best_dist and displacement < best_displacement):
            best = candidate
            best_dist = dist

    dx = patch.x - best.x
    dy = patch.y - best.y
    drift = _round6((abs(dx) + abs(dy)) / 2.0)
    return (dx, dy, drift)


def _feature_distance(a: PatchFlow, b: PatchFlow) -> float:
    return (
        abs(a.red - b.red)
        + abs(a.green - b.green)
        + abs(a.blue - b.blue)
        + abs(a.power - b.power)
        + abs(a.contrast - b.contrast)
    )


def _clamp_u8(value: int) -> int:
    if value < 0:
        return 0
    if value > 255:
        return 255
    return value


def _round6(value: float) -> float:
    return round(value * 1_000_000) / 1_000_000
