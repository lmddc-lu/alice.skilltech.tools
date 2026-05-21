#!/usr/bin/env python3
"""Generate CREDITS.md from direct runtime dependencies of the Python and frontend projects.

Usage: python3 scripts/generate_credits.py

Requires `uv` on PATH (used to invoke `pip-licenses` inside each project's venv)
and frontend `node_modules` installed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_PKG = ROOT / "frontend" / "package.json"
NODE_MODULES = ROOT / "frontend" / "node_modules"
OUTPUT = ROOT / "CREDITS.md"

# (section title, project directory containing pyproject.toml + .venv)
PY_PROJECTS: list[tuple[str, Path]] = [
    ("Api dependencies", ROOT / "api"),
    ("RAG pipeline dependencies", ROOT / "services" / "rag-pipeline"),
    ("Sync worker dependencies", ROOT / "sync" / "worker"),
]

# Third-party Docker images referenced from Dockerfiles and docker-compose files.
# Hand-curated: image license metadata isn't queryable in a standard way, and full
# license texts aren't meaningful for multi-component images. Each entry lists the
# pinned tag actually used, the SPDX-ish license identifier(s), and an upstream URL.
DOCKER_IMAGES: list[dict[str, str]] = [
    # Build / base images (Dockerfiles)
    {
        "image": "python:3.13-slim",
        "license": "PSF-2.0 (Python) + various (Debian base packages)",
        "url": "https://docs.python.org/3/license.html",
    },
    {
        "image": "node:lts-alpine",
        "license": "MIT (Node.js core) + various (Alpine base packages)",
        "url": "https://github.com/nodejs/node/blob/main/LICENSE",
    },
    {
        "image": "nginx:alpine",
        "license": "BSD-2-Clause (nginx) + various (Alpine base packages)",
        "url": "https://github.com/nginx/nginx/blob/master/LICENSE",
    },
    {
        "image": "deepset/hayhooks:v1.19.2",
        "license": "Apache-2.0",
        "url": "https://github.com/deepset-ai/hayhooks",
    },
    # Runtime service images (docker-compose)
    {
        "image": "postgres:17",
        "license": "PostgreSQL License (OSI-approved, BSD/MIT-style)",
        "url": "https://www.postgresql.org/about/licence/",
    },
    {
        "image": "redis:8-alpine",
        "license": "RSALv2 OR SSPLv1 OR AGPL-3.0 (tri-license, Redis 8.0+)",
        "url": "https://redis.io/legal/licenses/",
    },
    {
        "image": "rabbitmq:4.2.1-management",
        "license": "MPL-2.0 (core/tier-1 plugins) + Apache-2.0 (some OCF files)",
        "url": "https://github.com/rabbitmq/rabbitmq-server/blob/main/LICENSE",
    },
    {
        "image": "adminer",
        "license": "Apache-2.0 OR GPL-2.0",
        "url": "https://github.com/vrana/adminer/blob/master/LICENSE",
    },
    {
        "image": "dxflrs/garage:v2.1.0",
        "license": "AGPL-3.0",
        "url": "https://garagehq.deuxfleurs.fr/",
    },
    {
        "image": "khairul169/garage-webui:latest",
        "license": "MIT",
        "url": "https://github.com/khairul169/garage-webui",
    },
    {
        "image": "qdrant/qdrant:v1.17",
        "license": "Apache-2.0",
        "url": "https://github.com/qdrant/qdrant",
    },
    {
        "image": "ghcr.io/docling-project/docling-serve:v1.20.0",
        "license": "MIT",
        "url": "https://github.com/docling-project/docling-serve",
    },
    {
        "image": "ghcr.io/docling-project/docling-serve-cu130:v1.20.0",
        "license": "MIT",
        "url": "https://github.com/docling-project/docling-serve",
    },
    {
        "image": "mcr.microsoft.com/presidio-analyzer:2.2.362",
        "license": "MIT",
        "url": "https://github.com/microsoft/presidio",
    },
    {
        "image": "mcr.microsoft.com/presidio-anonymizer:2.2.362",
        "license": "MIT",
        "url": "https://github.com/microsoft/presidio",
    },
]


LICENSE_FILENAMES = [
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "license",
    "LICENCE",
    "LICENSE-MIT",
]


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


SEP = "-" * 80


def py_direct_packages(project_dir: Path) -> list[str]:
    data = tomllib.loads((project_dir / "pyproject.toml").read_text())
    deps = data["project"]["dependencies"]
    names: list[str] = []
    for spec in deps:
        # Strip extras and version specifiers: "fastapi[standard]>=0.121" -> "fastapi"
        name = re.split(r"[\[<>=!~;\s]", spec, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return names


def collect_py_credits(project_dir: Path, packages: list[str]) -> list[dict]:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--with",
            "pip-licenses",
            "--directory",
            str(project_dir),
            "pip-licenses",
            "--format=json",
            "--with-license-file",
            "--no-license-path",
            "--packages",
            *packages,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def frontend_direct_packages() -> list[str]:
    pkg = json.loads(FRONTEND_PKG.read_text())
    return sorted((pkg.get("dependencies") or {}).keys())


def read_frontend_entry(name: str) -> tuple[str, str] | None:
    """Return (license_id, license_text) for a package in node_modules, or None."""
    pkg_dir = NODE_MODULES / name
    pkg_json = pkg_dir / "package.json"
    if not pkg_json.exists():
        return None
    try:
        meta = json.loads(pkg_json.read_text())
    except json.JSONDecodeError:
        return None

    lic = meta.get("license")
    if isinstance(lic, dict):
        license_id = lic.get("type", "UNKNOWN")
    elif isinstance(lic, list):
        license_id = " OR ".join(
            (entry.get("type") if isinstance(entry, dict) else str(entry))
            for entry in lic
        )
    elif isinstance(lic, str):
        license_id = lic
    elif meta.get("licenses"):
        ls = meta["licenses"]
        if isinstance(ls, list):
            license_id = " OR ".join(
                (e.get("type") if isinstance(e, dict) else str(e)) for e in ls
            )
        else:
            license_id = str(ls)
    else:
        license_id = "UNKNOWN"

    text = ""
    for fname in LICENSE_FILENAMES:
        fpath = pkg_dir / fname
        if fpath.exists():
            try:
                text = fpath.read_text(errors="replace")
            except OSError:
                pass
            break
    return license_id, text


def format_block(name: str, license_id: str, text: str) -> str:
    text = (text or "").strip()
    body = f"\n{text}\n" if text else "\n"
    return f'{SEP}\nPackage: {name}\nLicense: "{license_id}"\n{body}'


def main() -> int:
    out: list[str] = []

    for title, project_dir in PY_PROJECTS:
        out.append(f"# {title}\n")
        pkgs = py_direct_packages(project_dir)
        entries = collect_py_credits(project_dir, pkgs)
        by_name = {normalize(e["Name"]): e for e in entries}
        for name in pkgs:
            entry = by_name.get(normalize(name))
            if entry is None:
                print(
                    f"warning: {project_dir.name} package not found in env: {name}",
                    file=sys.stderr,
                )
                continue
            out.append(
                format_block(
                    entry["Name"], entry["License"], entry.get("LicenseText", "")
                )
            )
        out.append("")

    out.append("# Frontend dependencies\n")

    for name in frontend_direct_packages():
        result = read_frontend_entry(name)
        if result is None:
            print(
                f"warning: frontend package not found in node_modules: {name}",
                file=sys.stderr,
            )
            continue
        license_id, text = result
        out.append(format_block(name, license_id, text))

    out.append(SEP)
    out.append("")
    out.append("# Docker images\n")
    for entry in DOCKER_IMAGES:
        out.append(
            f'{SEP}\nImage: {entry["image"]}\nLicense: "{entry["license"]}"\nUpstream: {entry["url"]}\n'
        )
    out.append(SEP + "\n")
    OUTPUT.write_text("\n".join(out))
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
