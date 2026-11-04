"""A portable OpenAPI contract assembled from the canonical message schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .protocol import schema


def openapi() -> dict[str, Any]:
    """Return a self-contained OpenAPI 3.1 document for QTP HTTP services.

    The authored document references the neighboring JSON Schema. Bundling its
    definitions here keeps downloads and JavaScript consumers independent of
    external schema resolution while retaining one authored message contract.
    """
    path = Path(__file__).with_name("openapi.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    definitions = document["components"]["schemas"]
    for name, definition in schema()["$defs"].items():
        definitions[name] = _references(definition)
    return document


def _references(value: Any) -> Any:
    if isinstance(value, list):
        return [_references(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                item.replace("#/$defs/", "#/components/schemas/", 1)
                if key == "$ref"
                and isinstance(item, str)
                and item.startswith("#/$defs/")
                else _references(item)
            )
            for key, item in value.items()
        }
    return value
