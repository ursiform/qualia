"""Qualia: Qualia Transmission Protocol (QTP) and sensorimotor Python client."""

from __future__ import annotations

from .client import Client, DEFAULT_URL, connect
from .local import LocalEngine
from .protocol import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MOTOR_ACTIONS,
    QTP_VERSION,
    Action,
    Consequence,
    Intention,
    Mode,
    Pattern,
    Percept,
    Phase,
    schema,
)
from .retina import PatchFlow, Retina, center_of_mass_x, extract_patches
from .specification import openapi
from .transport import TransportError, is_pyodide
from .validation import ProtocolError

__version__ = "0.4.0"

__all__ = [
    "Action",
    "Client",
    "Consequence",
    "DEFAULT_HEIGHT",
    "DEFAULT_URL",
    "DEFAULT_WIDTH",
    "Intention",
    "LocalEngine",
    "MOTOR_ACTIONS",
    "Mode",
    "PatchFlow",
    "Pattern",
    "Percept",
    "Phase",
    "QTP_VERSION",
    "ProtocolError",
    "Retina",
    "TransportError",
    "__version__",
    "center_of_mass_x",
    "connect",
    "extract_patches",
    "is_pyodide",
    "openapi",
    "schema",
]
