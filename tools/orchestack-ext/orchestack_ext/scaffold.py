"""Scaffolding templates for new Orchestack extensions."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# YAML templates per extension type
# ---------------------------------------------------------------------------

def _tool_manifest(name: str) -> dict[str, Any]:
    return {
        "apiVersion": "orchestack.io/v1alpha1",
        "kind": "Extension",
        "metadata": {
            "name": name,
            "version": "0.1.0",
            "description": f"{name} tool extension",
            "author": "Your Name",
            "license": "Apache-2.0",
            "tags": ["tool"],
            "trustTier": 2,
        },
        "spec": {
            "type": "tool",
            "toolDescriptor": {
                "tool_id": name,
                "name": name.replace("-", " ").title(),
                "description": f"TODO: describe what {name} does",
                "input_schema": {"type": "object", "properties": {}},
                "output_schema": {"type": "object", "properties": {}},
                "risk_class": "read_only",
                "idempotency": "idempotent",
                "capabilities": [],
                "data_classification": "internal",
                "audit_level": "metadata",
            },
            "runtime": "sandbox",
            "artifacts": {
                "containerfile": "Containerfile",
                "resources": {
                    "cpu_limit": "0.5",
                    "memory_limit": "256Mi",
                    "timeout_seconds": 30,
                },
            },
        },
        "security": {
            "signing": {"required": True},
            "network": {"egress_allowed": []},
        },
    }


def _skill_manifest(name: str) -> dict[str, Any]:
    return {
        "apiVersion": "orchestack.io/v1alpha1",
        "kind": "Extension",
        "metadata": {
            "name": name,
            "version": "0.1.0",
            "description": f"{name} skill extension",
            "author": "Your Name",
            "license": "Apache-2.0",
            "tags": ["skill"],
            "trustTier": 2,
        },
        "spec": {
            "type": "skill",
            "steps": [
                {"name": "step-1", "tool": "shell-exec", "prompt": "TODO"},
            ],
            "parameters": {"type": "object", "properties": {}},
            "guardrails": {
                "max_steps": 20,
                "max_cost_usd": 1.0,
                "require_approval": [],
                "forbidden_tools": [],
            },
        },
    }


def _schedule_manifest(name: str) -> dict[str, Any]:
    return {
        "apiVersion": "orchestack.io/v1alpha1",
        "kind": "Extension",
        "metadata": {
            "name": name,
            "version": "0.1.0",
            "description": f"{name} scheduled task",
            "author": "Your Name",
            "license": "Apache-2.0",
            "tags": ["schedule"],
            "trustTier": 2,
        },
        "spec": {
            "type": "schedule",
            "cron": "0 * * * *",
            "timezone": "UTC",
            "concurrency_policy": "forbid",
            "missed_run_policy": "skip",
            "task_template": {
                "tool": "TODO-tool-id",
                "input": {},
            },
        },
    }


def _connector_manifest(name: str) -> dict[str, Any]:
    return {
        "apiVersion": "orchestack.io/v1alpha1",
        "kind": "Extension",
        "metadata": {
            "name": name,
            "version": "0.1.0",
            "description": f"{name} connector extension",
            "author": "Your Name",
            "license": "Apache-2.0",
            "tags": ["connector"],
            "trustTier": 2,
        },
        "spec": {
            "type": "connector",
            "connector_type": "inbound",
            "protocol": "rest",
        },
        "security": {
            "signing": {"required": True},
            "network": {"egress_allowed": []},
        },
    }


_MANIFEST_BUILDERS: dict[str, Any] = {
    "tool": _tool_manifest,
    "skill": _skill_manifest,
    "schedule": _schedule_manifest,
    "connector": _connector_manifest,
}

SUPPORTED_TYPES = list(_MANIFEST_BUILDERS.keys())


def _containerfile_content() -> str:
    return textwrap.dedent("""\
        FROM python:3.12-slim

        WORKDIR /app
        COPY src/ ./src/
        COPY requirements.txt .

        RUN pip install --no-cache-dir -r requirements.txt

        ENTRYPOINT ["python", "-m", "src.main"]
    """)


def _readme_content(name: str, ext_type: str) -> str:
    return textwrap.dedent(f"""\
        # {name}

        Orchestack **{ext_type}** extension.

        ## Quick start

        ```bash
        # Lint the manifest
        orchestack-ext lint extension.yaml

        # Build the OCI image (tool / connector types)
        orchestack-ext build
        ```

        ## Structure

        ```
        {name}/
        ├── extension.yaml   # Extension manifest
        ├── Containerfile     # OCI build file (if applicable)
        ├── README.md
        └── src/
            └── main.py
        ```
    """)


def _main_py_content(name: str) -> str:
    return textwrap.dedent(f"""\
        \"\"\"Entry-point for the {name} extension.\"\"\"


        def main() -> None:
            print("Hello from {name}")


        if __name__ == "__main__":
            main()
    """)


def scaffold_extension(
    name: str,
    ext_type: str,
    output_dir: Path | None = None,
) -> Path:
    """Create the directory tree for a new extension.

    Returns the path to the created extension directory.
    """
    if ext_type not in _MANIFEST_BUILDERS:
        raise ValueError(
            f"Unknown extension type '{ext_type}'. "
            f"Supported: {', '.join(SUPPORTED_TYPES)}"
        )

    base = (output_dir or Path.cwd()) / name
    base.mkdir(parents=True, exist_ok=True)

    # extension.yaml
    manifest = _MANIFEST_BUILDERS[ext_type](name)
    (base / "extension.yaml").write_text(
        yaml.dump(manifest, default_flow_style=False, sort_keys=False)
    )

    # README.md
    (base / "README.md").write_text(_readme_content(name, ext_type))

    # src/
    src_dir = base / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "__init__.py").write_text("")
    (src_dir / "main.py").write_text(_main_py_content(name))

    # Containerfile for tier 1/2 (tool & connector)
    if ext_type in ("tool", "connector"):
        (base / "Containerfile").write_text(_containerfile_content())
        (base / "requirements.txt").write_text("# Add your dependencies here\n")

    return base
