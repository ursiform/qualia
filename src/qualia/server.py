"""Loopback QTP reference service with one deterministic demonstration session.

Run ``python -m qualia.server --port 8001 --seed 17``. Restart the process for a
fresh session. This service does not load or control another decision runtime.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from . import __version__
from .local import LocalEngine
from .protocol import Consequence, MOTOR_ACTIONS, Percept, QTP_VERSION
from .specification import openapi
from .validation import ProtocolError, fields, integer


class Conflict(ProtocolError):
    """The request cannot belong to the current session position."""


class Server(ThreadingHTTPServer):
    """One serialized QTP session, served only on IPv4 loopback."""

    daemon_threads = True

    def __init__(
        self, port: int = 8001, *, seed: int = 20261104, origins: tuple[str, ...] = ()
    ) -> None:
        port = integer(port, "port")
        if port > 65535:
            raise ValueError("port must be <= 65535")
        self.engine = LocalEngine(seed=seed)
        self.origins = frozenset(_origin(value) for value in origins)
        self.contract = openapi()
        self.limit = self.contract["paths"]["/api/qtp/step"]["post"][
            "x-reference-limit"
        ]
        self.lock = Lock()
        super().__init__(("127.0.0.1", port), Handler)

    def status(self) -> dict[str, Any]:
        """Read a coherent status without advancing the session."""
        with self.lock:
            status = self.engine.status()
            return {
                **status,
                "engine": "reference",
                "policy": "reflex",
                "seed": self.engine.seed,
                "last_action": status["last_action"] if status["steps"] else None,
            }

    def step(self, payload: Any) -> dict[str, Any]:
        """Validate first, then integrate exactly the next declared decision."""
        fields(payload, ("protocol", "step", "percept"), ("action", "consequence"))
        if payload["protocol"] != QTP_VERSION:
            raise ProtocolError("Expected protocol qtp/1.0")
        step = integer(payload["step"], "step")
        frame = Percept.from_dict(payload["percept"])
        action = payload.get("action")
        if action is not None and action not in (*MOTOR_ACTIONS, "still"):
            raise ProtocolError("Invalid preceding action")
        raw_outcome = payload.get("consequence")
        outcome = (
            Consequence.from_dict(raw_outcome) if raw_outcome is not None else None
        )
        if step == 0 and (action is not None or outcome is not None):
            raise ProtocolError("Step 0 has no preceding action or outcome")
        if step > 0 and action is None:
            raise ProtocolError("Later steps must name the preceding action")
        with self.lock:
            if step != self.engine.step_count:
                raise Conflict(f"Expected step {self.engine.step_count}, got {step}")
            if step and action != self.engine.status()["last_action"]:
                raise Conflict("Preceding action does not match the last intention")
            return self.engine.step(frame, outcome, step=step, fallback=False).to_dict()


class Handler(BaseHTTPRequestHandler):
    """Resolve fixed QTP operations from OpenAPI and translate HTTP only."""

    server_version = f"Qualia/{__version__}"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5.0)

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_TRACE(self) -> None:
        self._dispatch()

    def do_CONNECT(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.server.origins:
            self._error(403, "origin", "Origin is not configured for this service")
            return
        route = self.server.contract["paths"].get(urlsplit(self.path).path)
        if route is None:
            self._error(404, "resource", "Unknown QTP resource")
            return
        operation = route.get(self.command.lower())
        if operation is None:
            self._error(
                405, "method", "Method is not supported", {"Allow": _methods(route)}
            )
            return
        if self.command == "OPTIONS":
            self._preflight(route)
            return
        name = operation["operationId"]
        if name == "status":
            self._reply(200, self.server.status())
        elif name == "specification":
            self._reply(200, self.server.contract)
        elif name == "step":
            try:
                payload = self._read()
                intention = self.server.step(payload)
            except HTTPFailure as exc:
                self._error(exc.status, exc.code, str(exc))
            except Conflict as exc:
                self._error(
                    409, "sequence", str(exc), step=self.server.status()["steps"]
                )
            except (ValueError, RecursionError) as exc:
                self._error(400, "request", str(exc))
            except TimeoutError:
                self._error(400, "request", "Request body timed out")
            else:
                self._reply(200, intention)
        else:
            raise RuntimeError(f"No reference implementation for operation {name}")

    def _read(self) -> Any:
        if self.headers.get_content_type() != "application/json":
            raise HTTPFailure(415, "media", "Expected application/json")
        if self.headers.get("Transfer-Encoding") is not None:
            raise HTTPFailure(400, "request", "Transfer-Encoding is not supported")
        lengths = self.headers.get_all("Content-Length", [])
        if not lengths:
            raise HTTPFailure(411, "length", "Content-Length is required")
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            raise HTTPFailure(400, "length", "Invalid Content-Length")
        length = int(lengths[0])
        if length > self.server.limit:
            raise HTTPFailure(413, "length", "Request exceeds the reference body limit")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise HTTPFailure(400, "length", "Incomplete request body")
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant
        )

    def _preflight(self, route: dict[str, Any]) -> None:
        if self.headers.get("Origin") is None:
            self._error(400, "origin", "Preflight requires an Origin header")
            return
        requested = self.headers.get("Access-Control-Request-Method", "")
        if requested not in {method.upper() for method in route if method != "options"}:
            self._error(
                405,
                "method",
                "Preflight method is not supported",
                {"Allow": _methods(route)},
            )
            return
        headers = {
            value.strip().lower()
            for value in self.headers.get("Access-Control-Request-Headers", "").split(
                ","
            )
            if value.strip()
        }
        if not headers <= {"content-type", "accept"}:
            self._error(403, "headers", "Preflight headers are not allowed")
            return
        self._reply(
            204,
            None,
            {
                "Access-Control-Allow-Methods": _methods(route),
                "Access-Control-Allow-Headers": "Content-Type, Accept",
                "Access-Control-Allow-Private-Network": "true",
            },
        )

    def _error(
        self,
        status: int,
        code: str,
        detail: str,
        headers: dict[str, str] | None = None,
        *,
        step: int | None = None,
    ) -> None:
        payload = {"error": code, "detail": detail}
        if step is not None:
            payload["step"] = step
        self._reply(status, payload, headers)

    def _reply(
        self, status: int, payload: Any, headers: dict[str, str] | None = None
    ) -> None:
        raw = (
            b""
            if payload is None
            else json.dumps(payload, allow_nan=False).encode("utf-8")
        )
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        if status != 204:
            self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("Vary", "Origin")
        origin = getattr(self, "headers", {}).get("Origin")
        if origin in self.server.origins:
            self.send_header("Access-Control-Allow-Origin", origin)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A lost reply does not undo a completed session step.

    def send_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        self._error(code, "request", message or "HTTP request failed")

    def log_message(self, format: str, *args: Any) -> None:
        pass


class HTTPFailure(ValueError):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code


def _methods(route: dict[str, Any]) -> str:
    return ", ".join(method.upper() for method in route)


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Origins must be exact http(s) origins without paths or credentials"
        )
    parsed.port  # Validate a supplied port before binding the listener.
    return value


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ProtocolError(f"Non-finite JSON value: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the loopback QTP reflex reference service"
    )
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--seed", type=int, default=20261104)
    parser.add_argument(
        "--origin",
        action="append",
        default=[],
        help="Explicitly allow a browser origin; repeat for multiple origins",
    )
    args = parser.parse_args()
    try:
        server = Server(args.port, seed=args.seed, origins=tuple(args.origin))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"qualia: {exc}\n")
    with server:
        print(
            f"QTP reference policy=reflex seed={args.seed} http://127.0.0.1:{server.server_port}",
            flush=True,
        )
        try:
            server.serve_forever(poll_interval=0.1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
