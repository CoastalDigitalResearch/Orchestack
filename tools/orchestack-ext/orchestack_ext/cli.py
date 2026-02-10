"""Orchestack extension CLI -- lint, init, build, verify, list."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from orchestack_ext.scaffold import SUPPORTED_TYPES, scaffold_extension
from orchestack_ext.schema import load_manifest, validate_manifest

console = Console()


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="orchestack-ext")
def cli() -> None:
    """orchestack-ext -- Orchestack extension manifest toolkit."""


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("path", type=click.Path(exists=True))
def lint(path: str) -> None:
    """Validate an extension.yaml against the Orchestack JSON Schema."""
    errors = validate_manifest(Path(path))
    if not errors:
        console.print(f"[bold green]PASS[/bold green]  {path}")
        return
    console.print(f"[bold red]FAIL[/bold red]  {path}  ({len(errors)} error(s))")
    for err in errors:
        console.print(f"  [yellow]{err.path}[/yellow]: {err.message}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("ext_type", type=click.Choice(SUPPORTED_TYPES, case_sensitive=False))
@click.option("--name", "-n", prompt="Extension name", help="Name for the new extension")
@click.option("--output-dir", "-o", type=click.Path(), default=None, help="Parent directory")
def init(ext_type: str, name: str, output_dir: str | None) -> None:
    """Scaffold a new extension (tool / skill / schedule / connector)."""
    out = Path(output_dir) if output_dir else None
    try:
        created = scaffold_extension(name, ext_type, output_dir=out)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)
    console.print(f"[bold green]Created[/bold green] {ext_type} extension at [cyan]{created}[/cyan]")
    console.print("Next steps:")
    console.print(f"  cd {created}")
    console.print("  # Edit extension.yaml, then:")
    console.print("  orchestack-ext lint extension.yaml")


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--tag", "-t", default=None, help="Image tag (default: <name>:<version>)")
@click.option("--containerfile", "-f", default="Containerfile", help="Path to Containerfile")
def build(tag: str | None, containerfile: str) -> None:
    """Build an OCI image for the current extension (shells out to docker/podman)."""
    manifest_path = Path("extension.yaml")
    if not manifest_path.exists():
        console.print("[bold red]Error:[/bold red] No extension.yaml found in current directory")
        sys.exit(1)

    manifest = load_manifest(manifest_path)
    meta = manifest.get("metadata", {})
    name = meta.get("name", "extension")
    version = meta.get("version", "latest")
    image_tag = tag or f"{name}:{version}"

    # Prefer podman, fall back to docker
    runtime = "podman" if shutil.which("podman") else "docker"
    if not shutil.which(runtime):
        console.print(
            "[bold red]Error:[/bold red] Neither podman nor docker found on PATH"
        )
        sys.exit(1)

    cmd = [runtime, "build", "-t", image_tag, "-f", containerfile, "."]
    console.print(f"[bold blue]Building[/bold blue] {image_tag} with {runtime} ...")
    console.print(f"  $ {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        console.print(f"[bold red]Build failed[/bold red] (exit {result.returncode})")
        sys.exit(result.returncode)
    console.print(f"[bold green]Built[/bold green] {image_tag}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("image")
@click.option("--key", "-k", default=None, help="Path to cosign public key")
def verify(image: str, key: str | None) -> None:
    """Verify the cosign signature of an OCI image."""
    if not shutil.which("cosign"):
        console.print("[bold red]Error:[/bold red] cosign not found on PATH")
        console.print("  Install: https://docs.sigstore.dev/cosign/installation/")
        sys.exit(1)

    cmd = ["cosign", "verify"]
    if key:
        cmd += ["--key", key]
    cmd.append(image)

    console.print(f"[bold blue]Verifying[/bold blue] {image} ...")
    console.print(f"  $ {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[bold red]Verification FAILED[/bold red]")
        if result.stderr:
            console.print(result.stderr.strip())
        sys.exit(result.returncode)
    console.print(f"[bold green]Verified[/bold green] {image}")
    if result.stdout:
        console.print(result.stdout.strip())


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@cli.command(name="list")
@click.option("--dir", "-d", "directory", default=".", help="Directory to scan")
def list_extensions(directory: str) -> None:
    """List Orchestack extensions found in a directory tree."""
    root = Path(directory).resolve()
    manifests: list[tuple[Path, dict]] = []

    for manifest_path in sorted(root.rglob("extension.yaml")):
        try:
            data = load_manifest(manifest_path)
            if (
                isinstance(data, dict)
                and data.get("apiVersion") == "orchestack.io/v1alpha1"
                and data.get("kind") == "Extension"
            ):
                manifests.append((manifest_path, data))
        except Exception:
            continue

    if not manifests:
        console.print("[dim]No Orchestack extensions found.[/dim]")
        return

    table = Table(title="Orchestack Extensions", show_lines=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Type", style="magenta")
    table.add_column("Trust", justify="center")
    table.add_column("Path", style="dim")

    for mpath, data in manifests:
        meta = data.get("metadata", {})
        spec = data.get("spec", {})
        name = meta.get("name", "?")
        version = meta.get("version", "?")
        ext_type = spec.get("type", "?")
        trust = str(meta.get("trustTier", "?"))
        rel = str(mpath.relative_to(root)) if mpath.is_relative_to(root) else str(mpath)
        table.add_row(name, version, ext_type, trust, rel)

    console.print(table)
