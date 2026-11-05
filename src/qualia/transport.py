"""Bounded JSON transport for CPython and browser-hosted Python."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Mapping
import urllib.request

from .validation import ProtocolError, number


class TransportError(RuntimeError):
    """An HTTP, reachability, or timeout failure; never a valid decision."""

    def __init__(
        self, message: str, *, status: int | None = None, timed_out: bool = False
    ) -> None:
        super().__init__(message)
        self.status = status
        self.timed_out = timed_out


def is_pyodide() -> bool:
    """Return whether Python is running in the browser environment."""
    return sys.platform == "emscripten" or "pyodide" in sys.modules


def _invalid_number(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def _decode(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeError as exc:
            raise ProtocolError("Response is not UTF-8 JSON") from exc
    try:
        parsed = json.loads(raw, parse_constant=_invalid_number)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("Expected a JSON object response") from exc
    if not isinstance(parsed, dict):
        raise ProtocolError("Expected a JSON object response")
    return parsed


def timeout_value(value: float) -> float:
    number(value, "timeout", 0.0)
    if value == 0:
        raise ValueError("timeout must be positive")
    return float(value)


def request_json_sync(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Make one HTTP request without retrying a potentially accepted step."""
    from ._http import HTTPFailure, read_response

    timeout = timeout_value(timeout)
    req_headers = {"Accept": "application/json", **(headers or {})}
    body = None
    if payload is not None:
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        url, data=body, headers=req_headers, method=method.upper()
    )
    try:
        status, body = read_response(request, timeout)
        if not 200 <= status < 300:
            raise TransportError(f"HTTP {status} from {url}", status=status)
        raw = body.decode("utf-8")
    except HTTPFailure as exc:
        raise TransportError(
            f"QTP transport error for {url}: {exc}",
            status=exc.status,
            timed_out=exc.timed_out,
        ) from exc
    except UnicodeError as exc:
        raise ProtocolError("Response is not UTF-8 JSON") from exc
    return _decode(raw)


async def request_json_async(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Use bounded browser fetch or offload the standard-library request."""
    timeout = timeout_value(timeout)
    if is_pyodide():
        return await _pyfetch_json(
            url, method=method, payload=payload, headers=headers, timeout=timeout
        )
    return await asyncio.to_thread(
        request_json_sync,
        url,
        method=method,
        payload=payload,
        headers=headers,
        timeout=timeout,
    )


async def _pyfetch_json(
    url: str,
    *,
    method: str,
    payload: Mapping[str, Any] | None,
    headers: Mapping[str, str] | None,
    timeout: float,
) -> dict[str, Any]:
    from js import AbortController  # type: ignore[import-not-found]
    from pyodide.http import pyfetch  # type: ignore[import-not-found]

    controller = AbortController.new()
    req_headers = {"Accept": "application/json", **(headers or {})}
    kwargs: dict[str, Any] = {
        "method": method.upper(),
        "headers": req_headers,
        "signal": controller.signal,
    }
    if payload is not None:
        kwargs["body"] = json.dumps(payload, allow_nan=False)
        req_headers.setdefault("Content-Type", "application/json")

    status = None

    async def exchange() -> dict[str, Any]:
        nonlocal status
        response = await pyfetch(url, **kwargs)
        status = int(response.status)
        if not 200 <= status < 300:
            controller.abort()
            raise TransportError(f"HTTP {status} from {url}", status=status)
        return _decode(await response.bytes())

    try:
        return await asyncio.wait_for(exchange(), timeout)
    except asyncio.TimeoutError as exc:
        controller.abort()
        raise TransportError(
            f"QTP request timed out after {timeout}s", status=status, timed_out=True
        ) from exc
    except asyncio.CancelledError:
        controller.abort()
        raise
    except (TransportError, ProtocolError):
        raise
    except Exception as exc:
        raise TransportError(
            f"QTP pyfetch error for {url}: {exc}", status=status
        ) from exc
