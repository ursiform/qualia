"""Standalone deterministic sensorimotor reflex engine for local QTP execution."""

from __future__ import annotations

from typing import Any

from .protocol import Action, Consequence, Intention, Percept
from .retina import PatchFlow, extract_patches
from .validation import ProtocolError, boolean, integer

DEFAULT_CANDIDATES = 366


class LocalEngine:
    """Deterministic local sensorimotor driver implementing the QTP step contract.

    Used when ``mode="local"`` is explicitly selected or when ``mode="auto"``
    cannot reach a remote QTP server. Evaluates spatial patch luminance,
    contrast, and frame-to-frame optical flow across left, center, and right
    visual fields, and applies turn-recovery streaks when forward motion is
    obstructed.
    """

    def __init__(
        self,
        *,
        seed: int = 20261104,
        candidates_per_pool: int = DEFAULT_CANDIDATES,
    ) -> None:
        self.seed = integer(seed, "seed")
        self.candidates_per_pool = integer(
            candidates_per_pool, "candidates_per_pool", 1
        )
        self._step = 0
        self._streak = 0
        self._last_action: Action = "still"
        self._previous_patches: list[PatchFlow] | None = None
        self._decisions: dict[str, int] = {
            "left": 0,
            "right": 0,
            "forward": 0,
        }

    @property
    def step_count(self) -> int:
        """Total sensorimotor steps processed by this engine."""
        return self._step

    @property
    def streak(self) -> int:
        """Current consecutive blocked-forward recovery streak."""
        return self._streak

    def reset(self) -> None:
        """Reset retained patch flow history, step counter, and streak state."""
        self._step = 0
        self._streak = 0
        self._last_action = "still"
        self._previous_patches = None
        self._decisions = {"left": 0, "right": 0, "forward": 0}

    def status(self) -> dict[str, Any]:
        """Return a status snapshot matching the QTP status contract."""
        return {
            "protocol": "qtp/1.0",
            "engine": "local",
            "ready": True,
            "steps": self._step,
            "streak": self._streak,
            "last_action": self._last_action,
            "decisions": dict(self._decisions),
        }

    def step(
        self,
        percept: Percept,
        consequence: Consequence | None = None,
        *,
        step: int | None = None,
        fallback: bool = True,
    ) -> Intention:
        """Process one Percept and optional preceding Consequence into an Intention."""
        step_index = self._step if step is None else integer(step, "step")
        boolean(fallback, "fallback")

        patches = self._receive(percept, consequence)

        left_patches = [p for p in patches if p.x < 5]
        center_patches = [p for p in patches if 5 <= p.x < 11]
        right_patches = [p for p in patches if p.x >= 11]

        left_drive = _pool_drive(left_patches)
        center_drive = _pool_drive(center_patches)
        right_drive = _pool_drive(right_patches)

        # These demonstration counts are synthetic, not remote activity measurements
        raw_scores: dict[str, float] = {
            "left": _clamp01(0.28 + 0.72 * left_drive),
            "right": _clamp01(0.28 + 0.72 * right_drive),
            "forward": _clamp01(0.30 + 0.70 * center_drive),
        }

        if consequence is not None and consequence.completed:
            # Goal contact supports the action that just succeeded
            if self._last_action in raw_scores:
                raw_scores[self._last_action] = _clamp01(
                    raw_scores[self._last_action] + 0.15
                )

        if self._streak > 0:
            chosen = self._recovery_turn(step_index, raw_scores)
            raw_scores["forward"] = _round6(raw_scores["forward"] * 0.35)
            raw_scores[chosen] = _clamp01(max(raw_scores[chosen], 0.68))
        else:
            chosen = _select_action(raw_scores)

        candidates = {
            "left": self.candidates_per_pool,
            "right": self.candidates_per_pool,
            "forward": self.candidates_per_pool,
        }
        active = {
            pool: min(
                self.candidates_per_pool,
                max(1, int(round(score * self.candidates_per_pool))),
            )
            for pool, score in raw_scores.items()
        }
        scores = {pool: _round6(score) for pool, score in raw_scores.items()}

        self._record(chosen, step_index)

        return Intention(
            action=chosen,
            step=step_index,
            active=active,
            candidates=candidates,
            scores=scores,
            fallback=fallback,
        )

    def observe(
        self,
        percept: Percept,
        consequence: Consequence | None = None,
        *,
        action: Action,
        step: int | None = None,
    ) -> None:
        """Retain a real remote decision without inventing a shadow action."""
        if action not in ("left", "right", "forward", "still"):
            raise ProtocolError("Invalid observed action")
        step_index = self._step if step is None else integer(step, "step")
        self._receive(percept, consequence)
        self._record(action, step_index)

    def _receive(
        self, percept: Percept, consequence: Consequence | None
    ) -> list[PatchFlow]:
        if consequence is not None:
            if consequence.blocked and self._last_action in ("forward", "still"):
                self._streak += 1
            else:
                self._streak = 0

        patches = extract_patches(percept, self._previous_patches)
        self._previous_patches = patches

        return patches

    def _record(self, action: Action, step: int) -> None:
        self._last_action = action
        self._step = step + 1
        if action in self._decisions:
            self._decisions[action] += 1

    def _recovery_turn(self, step_index: int, scores: dict[str, float]) -> Action:
        diff = scores["right"] - scores["left"]
        if abs(diff) > 0.04:
            return "right" if diff > 0 else "left"
        # FNV-1a provides the same bounded tie-break in both client languages.
        word = 2166136261
        for byte in f"{self.seed}:{self._streak}:{step_index}".encode("ascii"):
            word = ((word ^ byte) * 16777619) & 0xFFFFFFFF
        return "left" if word % 2 == 0 else "right"


def _pool_drive(patches: list[PatchFlow]) -> float:
    if not patches:
        return 0.0
    total = 0.0
    for p in patches:
        flow_power = abs(p.delta)
        total += (
            0.55 * p.power
            + 0.20 * p.contrast
            + 0.15 * p.rise
            + 0.10 * max(flow_power, p.drift * 0.5)
        )
    return _round6(total / len(patches))


def _select_action(scores: dict[str, float]) -> Action:
    # Deterministic tie-breaking order: forward, left, right
    order: tuple[Action, ...] = ("forward", "left", "right")
    best_action: Action = "forward"
    best_score = -1.0
    for candidate in order:
        val = scores.get(candidate, 0.0)
        if val > best_score:
            best_score = val
            best_action = candidate
    return best_action


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _round6(value: float) -> float:
    return round(value * 1_000_000) / 1_000_000
