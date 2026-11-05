"""Small runtime checks shared by QTP's wire types."""

from __future__ import annotations

import math
from typing import Any, Mapping


class ProtocolError(ValueError):
    """A QTP message violates the wire contract."""


def integer(value: Any, name: str, minimum: int = 0) -> int:
    if (
        type(value) not in (int, float)
        or not minimum <= value <= 2**53 - 1
        or int(value) != value
    ):
        raise ProtocolError(f"{name} must be an integer in [{minimum}, {2**53 - 1}]")
    return int(value)


def number(value: Any, name: str, minimum: float = -math.inf) -> float:
    if type(value) not in (int, float):
        raise ProtocolError(f"{name} must be a finite number >= {minimum}")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ProtocolError(f"{name} is too large") from exc
    if not math.isfinite(result) or result < minimum:
        raise ProtocolError(f"{name} must be a finite number >= {minimum}")
    return result


def boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ProtocolError(f"{name} must be a boolean")
    return value


def fields(
    payload: Any, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ProtocolError("Expected a QTP object")
    missing = set(required) - payload.keys()
    extra = payload.keys() - set(required) - set(optional)
    if missing or extra:
        raise ProtocolError(
            f"Invalid QTP fields: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return payload


def pools(value: Any, name: str, *, counts: bool) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or not {"left", "right", "forward"} <= value.keys()
    ):
        raise ProtocolError(f"{name} must contain left, right, and forward pools")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ProtocolError(f"{name} keys must be strings")
        result[key] = integer(item, name) if counts else number(item, name)
    return result
