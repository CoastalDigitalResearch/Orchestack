"""Schema validation for Orchestack extension manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

# Resolve the schema path relative to this file -> ../../proto/
_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "proto"
_SCHEMA_PATH = _SCHEMA_DIR / "extension-manifest.schema.json"


@dataclass
class ValidationError:
    """A single validation error with location and message."""

    path: str
    message: str
    schema_path: str = ""

    def __str__(self) -> str:
        loc = self.path or "$"
        return f"  {loc}: {self.message}"


def _load_schema(schema_path: Path | None = None) -> dict[str, Any]:
    """Load the JSON Schema, resolving relative $ref within the schema."""
    path = schema_path or _SCHEMA_PATH
    if not path.exists():
        raise FileNotFoundError(f"Schema not found at {path}")
    with open(path) as f:
        return json.load(f)


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load a YAML or JSON manifest file."""
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    with open(path) as f:
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(f)
        else:
            return json.load(f)


def validate_manifest(
    manifest_path: Path | str,
    schema_path: Path | str | None = None,
) -> list[ValidationError]:
    """Validate an extension manifest against the JSON Schema.

    Returns a list of ValidationError objects.  An empty list means
    the manifest is valid.
    """
    manifest_path = Path(manifest_path)
    schema_path = Path(schema_path) if schema_path else None

    try:
        manifest = load_manifest(manifest_path)
    except FileNotFoundError as exc:
        return [ValidationError(path="", message=str(exc))]
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        return [ValidationError(path="", message=f"Parse error: {exc}")]

    if manifest is None:
        return [ValidationError(path="", message="Manifest file is empty")]

    try:
        schema = _load_schema(schema_path)
    except FileNotFoundError as exc:
        return [ValidationError(path="", message=str(exc))]

    # Build a resolver so that $ref "#/$defs/Foo" works correctly.
    # jsonschema 4.x+ uses Registry-based resolution.
    errors: list[ValidationError] = []
    validator_cls = jsonschema.Draft202012Validator
    validator = validator_cls(schema)

    for error in sorted(validator.iter_errors(manifest), key=lambda e: list(e.absolute_path)):
        json_path = ".".join(str(p) for p in error.absolute_path) or "$"
        schema_loc = ".".join(str(p) for p in error.absolute_schema_path)
        errors.append(
            ValidationError(
                path=json_path,
                message=error.message,
                schema_path=schema_loc,
            )
        )

    return errors
