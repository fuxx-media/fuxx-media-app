"""Phase 0.1 architecture and safety checks."""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ALLOWED_TOP_LEVEL = {
    ".dockerignore",
    ".env.example",
    ".github",
    ".gitignore",
    ".local-certs",
    "IMPLEMENTATION_PLAN.md",
    "Makefile",
    "PHASE_0_1_CONFLICT_REPORT.md",
    "PHASE_0_COMPLETION_REPORT.md",
    "README.md",
    "backend",
    "docker-compose.yml",
    "docs",
    "frontend",
    "package-lock.json",
    "package.json",
    "pyproject.toml",
    "scripts",
    "storage",
}

FORBIDDEN_DIRECT_DEPENDENCIES = {
    "celery",
    "cohere",
    "elasticsearch",
    "google-generativeai",
    "graphql",
    "kafka-python",
    "mistralai",
    "n8n",
    "openai",
    "pika",
    "rabbitmq",
    "redis",
    "replicate",
    "supabase",
    "temporalio",
}

FORBIDDEN_DB_MARKERS = (
    "DATABASE_URL_SECONDARY",
    "MYSQL",
    "MONGO",
    "PLATFORM_DATABASE_URL",
    "SQLITE",
    "SUPABASE",
)

SECRET_PATTERNS = {
    "aws access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"),
    "openai key": re.compile(r"sk-[A-Za-z0-9]{32,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |)PRIVATE KEY-----"),
}

TEXT_SUFFIXES = {
    ".css",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yml",
}


def iter_project_files() -> list[Path]:
    ignored_parts = {
        ".git",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
    files: list[Path] = []
    for directory, child_directories, filenames in os.walk(ROOT):
        child_directories[:] = [
            name
            for name in child_directories
            if name not in ignored_parts and not name.endswith(".egg-info")
        ]
        files.extend(Path(directory) / filename for filename in filenames)
    return sorted(files)


def fail(message: str) -> None:
    raise SystemExit(f"ARCHITECTURE CHECK FAILED: {message}")


def check_top_level(files: list[Path]) -> None:
    unexpected = sorted({path.relative_to(ROOT).parts[0] for path in files} - ALLOWED_TOP_LEVEL)
    if unexpected:
        fail(f"unexpected top-level entries: {', '.join(unexpected)}")


def check_direct_dependencies() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    python_dependencies = pyproject["project"].get("dependencies", [])
    optional_dependencies = pyproject["project"].get("optional-dependencies", {})
    names = []

    for dependency in python_dependencies:
        names.append(re.split(r"[<>=!~;[]", dependency, maxsplit=1)[0].strip().lower())
    for group in optional_dependencies.values():
        for dependency in group:
            names.append(re.split(r"[<>=!~;[]", dependency, maxsplit=1)[0].strip().lower())

    package_json = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        names.extend(name.lower() for name in package_json.get(section, {}))

    forbidden = sorted(FORBIDDEN_DIRECT_DEPENDENCIES.intersection(names))
    if forbidden:
        fail(f"forbidden direct dependencies present: {', '.join(forbidden)}")


def check_current_state_mutation(files: list[Path]) -> None:
    allowed = Path("backend/src/mediaos/application/workflow_transition_service.py")
    patterns = (
        re.compile(r"\.current_state\s*=(?!=)"),
        re.compile(r"setattr\([^)]*['\"]current_state['\"]"),
        re.compile(r"\.values\([^)]*current_state\s*="),
    )

    for path in files:
        relative = path.relative_to(ROOT)
        if relative == allowed or path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern.search(text):
                fail(f"direct current_state mutation outside transition service: {relative}")


def check_database_boundaries(files: list[Path]) -> None:
    inspected_suffixes = {".env", ".example", ".py", ".toml", ".yml"}
    for path in files:
        if path == Path(__file__).resolve():
            continue
        if path.suffix not in inspected_suffixes and path.name != ".env.example":
            continue
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8").upper()
        for marker in FORBIDDEN_DB_MARKERS:
            if marker in text:
                fail(f"forbidden database/platform marker {marker} in {relative}")


def check_secret_files(files: list[Path]) -> None:
    forbidden_names = {
        ".env",
        ".env.local",
        "id_rsa",
        "id_ed25519",
        "service-role.json",
        "service_role.json",
    }
    hits = []
    for path in files:
        relative = path.relative_to(ROOT)
        if path.name in forbidden_names:
            hits.append(str(relative))
    if hits:
        fail(f"secret-like files must not be committed: {', '.join(sorted(hits))}")


def check_secret_patterns(files: list[Path]) -> None:
    for path in files:
        if path.suffix not in TEXT_SUFFIXES and path.name != ".env.example":
            continue
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                fail(f"possible {label} in {relative}")


def main() -> None:
    files = iter_project_files()
    check_top_level(files)
    check_direct_dependencies()
    check_current_state_mutation(files)
    check_database_boundaries(files)
    check_secret_files(files)
    check_secret_patterns(files)
    print("Architecture guard passed.")


if __name__ == "__main__":
    main()
