"""QTP client session managing remote HTTP transport and local fallback routing."""

from __future__ import annotations

from typing import Any, Mapping

from .local import LocalEngine
from .protocol import (
    QTP_VERSION,
    Action,
    Consequence,
    Intention,
    Mode,
    Percept,
)
from .retina import Retina
from .validation import ProtocolError, boolean
from .transport import (
    TransportError,
    request_json_async,
    request_json_sync,
    timeout_value,
)

DEFAULT_URL = "http://127.0.0.1:8001"
DEFAULT_STEP_PATH = "/api/qtp/step"
DEFAULT_STATUS_PATH = "/api/status"


class Client:
    """Session client for the Qualia Transmission Protocol (QTP v1).

    Supports three operating modes:

    - ``"remote"``: Sends QTP JSON requests to ``url`` and raises
      :class:`~qualia.transport.TransportError` if the server is unreachable.
    - ``"local"``: Executes the deterministic in-process :class:`~qualia.local.LocalEngine`
      without making network calls.
    - ``"auto"``: Explicitly permits local decisions on network failure.
      HTTP, protocol, and timeout failures always raise errors.

    Remote operation is the default. The local engine is a demonstration policy;
    its pool counts are synthetic and do not measure a remote runtime.
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        mode: Mode = "remote",
        *,
        timeout: float = 2.0,
        step_path: str = DEFAULT_STEP_PATH,
        status_path: str = DEFAULT_STATUS_PATH,
        seed: int = 20261104,
    ) -> None:
        if mode not in ("auto", "remote", "local"):
            raise ValueError(
                f"Invalid mode {mode!r}; expected 'auto', 'remote', or 'local'"
            )
        self.url = url.rstrip("/")
        self.mode: Mode = mode
        self.timeout = timeout_value(timeout)
        self.step_path = "/" + step_path.lstrip("/")
        self.status_path = "/" + status_path.lstrip("/")
        self.retina = Retina()
        self.local = LocalEngine(seed=seed)
        self._step = 0
        self._last_action: Action | None = None

    @property
    def step_count(self) -> int:
        """Number of steps executed in this client session."""
        return self._step

    @property
    def last_action(self) -> Action | None:
        """The most recent action returned by ``step`` or ``step_sync``."""
        return self._last_action

    def reset(self) -> None:
        """Reset step counters, local reflex engine, and attached retina buffer."""
        self._step = 0
        self._last_action = None
        self.retina.reset()
        self.local.reset()

    async def step(
        self,
        percept: Percept | Mapping[str, Any],
        consequence: Consequence | Mapping[str, Any] | None = None,
    ) -> Intention:
        """Transmit one Percept and optional Consequence and await the resulting Intention."""
        frame, outcome, step_idx = self._prepare_step(percept, consequence)

        if self.mode == "local":
            intention = self.local.step(frame, outcome, step=step_idx, fallback=True)
            self._record_intention(intention, step_idx)
            return intention

        payload = self._build_request(frame, outcome, step_idx)
        target_url = f"{self.url}{self.step_path}"
        try:
            response = await request_json_async(
                target_url,
                method="POST",
                payload=payload,
                timeout=self.timeout,
            )
            intention = self._parse_intention(response, step_idx)
            self.local.observe(frame, outcome, action=intention.action, step=step_idx)
            self._record_intention(intention, step_idx)
            return intention
        except TransportError as exc:
            if self.mode == "remote" or exc.status is not None or exc.timed_out:
                raise
            intention = self.local.step(frame, outcome, step=step_idx, fallback=True)
            self._record_intention(intention, step_idx)
            return intention

    def step_sync(
        self,
        percept: Percept | Mapping[str, Any],
        consequence: Consequence | Mapping[str, Any] | None = None,
    ) -> Intention:
        """Synchronous counterpart to :meth:`step` for scripts and CLI drivers."""
        frame, outcome, step_idx = self._prepare_step(percept, consequence)

        if self.mode == "local":
            intention = self.local.step(frame, outcome, step=step_idx, fallback=True)
            self._record_intention(intention, step_idx)
            return intention

        payload = self._build_request(frame, outcome, step_idx)
        target_url = f"{self.url}{self.step_path}"
        try:
            response = request_json_sync(
                target_url,
                method="POST",
                payload=payload,
                timeout=self.timeout,
            )
            intention = self._parse_intention(response, step_idx)
            self.local.observe(frame, outcome, action=intention.action, step=step_idx)
            self._record_intention(intention, step_idx)
            return intention
        except TransportError as exc:
            if self.mode == "remote" or exc.status is not None or exc.timed_out:
                raise
            intention = self.local.step(frame, outcome, step=step_idx, fallback=True)
            self._record_intention(intention, step_idx)
            return intention

    async def status(self) -> dict[str, Any]:
        """Fetch server or local engine status asynchronously."""
        if self.mode == "local":
            return self.local.status()
        target_url = f"{self.url}{self.status_path}"
        try:
            remote_status = await request_json_async(
                target_url, method="GET", timeout=self.timeout
            )
            if remote_status.get("protocol") != QTP_VERSION:
                raise ProtocolError("Status does not advertise qtp/1.0")
            boolean(remote_status.get("ready"), "ready")
            return {
                **remote_status,
                "protocol": QTP_VERSION,
                "engine": "remote",
                "url": self.url,
            }
        except TransportError as exc:
            if self.mode == "remote" or exc.status is not None or exc.timed_out:
                raise
            return {**self.local.status(), "fallback": True}

    def status_sync(self) -> dict[str, Any]:
        """Fetch server or local engine status synchronously."""
        if self.mode == "local":
            return self.local.status()
        target_url = f"{self.url}{self.status_path}"
        try:
            remote_status = request_json_sync(
                target_url, method="GET", timeout=self.timeout
            )
            if remote_status.get("protocol") != QTP_VERSION:
                raise ProtocolError("Status does not advertise qtp/1.0")
            boolean(remote_status.get("ready"), "ready")
            return {
                **remote_status,
                "protocol": QTP_VERSION,
                "engine": "remote",
                "url": self.url,
            }
        except TransportError as exc:
            if self.mode == "remote" or exc.status is not None or exc.timed_out:
                raise
            return {**self.local.status(), "fallback": True}

    def _prepare_step(
        self,
        percept: Percept | Mapping[str, Any],
        consequence: Consequence | Mapping[str, Any] | None,
    ) -> tuple[Percept, Consequence | None, int]:
        frame = percept if isinstance(percept, Percept) else Percept.from_dict(percept)
        outcome = (
            None
            if consequence is None
            else (
                consequence
                if isinstance(consequence, Consequence)
                else Consequence.from_dict(consequence)
            )
        )
        step_idx = self._step
        return (frame, outcome, step_idx)

    def _build_request(
        self,
        percept: Percept,
        consequence: Consequence | None,
        step_idx: int,
    ) -> dict[str, Any]:
        return {
            "protocol": QTP_VERSION,
            "step": step_idx,
            "percept": percept.to_dict(),
            "consequence": consequence.to_dict() if consequence is not None else None,
            "action": self._last_action,
        }

    def _parse_intention(self, response: Mapping[str, Any], step_idx: int) -> Intention:
        if not isinstance(response, Mapping):
            raise ProtocolError("Expected a QTP response object")
        if "intention" in response:
            if set(response) != {"intention"}:
                raise ProtocolError("Invalid intention envelope")
            response = response["intention"]
        intention = Intention.from_dict(response)
        if intention.step != step_idx:
            raise ProtocolError(
                f"Expected response step {step_idx}, got {intention.step}"
            )
        if intention.fallback:
            raise ProtocolError("A remote response cannot claim local fallback")
        return intention

    def _record_intention(self, intention: Intention, step_idx: int) -> None:
        self._last_action = intention.action
        self._step = step_idx + 1


def connect(
    url: str = DEFAULT_URL,
    mode: Mode = "remote",
    *,
    timeout: float = 2.0,
    step_path: str = DEFAULT_STEP_PATH,
    status_path: str = DEFAULT_STATUS_PATH,
    seed: int = 20261104,
) -> Client:
    """Create a QTP :class:`Client` connected to ``url`` (or local fallback)."""
    return Client(
        url=url,
        mode=mode,
        timeout=timeout,
        step_path=step_path,
        status_path=status_path,
        seed=seed,
    )
