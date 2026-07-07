---
name: python-engineer
description: |
  Python development best practices for Python 3.14+ scripts, CLI tools, and small modules.
  Emphasizes type hints, clean structure, modern stdlib features, and explicit error handling.
  Triggers: writing Python scripts, Python CLI tools, small Python modules, Python file operations, Python environment setup, Python dependency installation, interpreter/pip mismatch diagnosis, and ModuleNotFoundError troubleshooting.
---

# Python Engineer

Target: Python 3.14+ by default. Check `sys.version_info` when version matters.

**Tooling**: Use `uv` (≥0.5) for all Python tasks—running scripts, managing dependencies, virtual environments.

Default style: optimize for clarity, simplicity, and correctness. Prefer straightforward runtime imports and explicit error handling over clever patterns or micro-optimizations.

## Environment First

When the user is trying to run Python on their machine, identify the active interpreter before prescribing package-install steps. Check:

```bash
which python3
python3 --version
python3 -m pip --version
python3 -c 'import sys; print(sys.executable)'
```

Do not assume `python3` maps to system Python, Homebrew Python, or a project venv. It may be `uv`-managed.

If the user says "with my current Python setup", tailor commands to that exact interpreter.

## Included Resources

This skill is self-contained and includes:
- [Python 3.13/3.14 Feature Reference](references/python_features_313_314.md) — Complete feature list for version-specific guidance

## Context Detection

**Personal script** (default): Single-file, 200-600 lines (typical size for focused CLI tools before needing modularization), CLI-focused, runs on macOS.
**Larger application**: Multiple modules, package structure, tests, CI/CD.

Signs of larger application:
- `pyproject.toml` or `setup.py` exists
- `src/` layout or package directories
- `tests/` directory
- Multiple `.py` files with imports between them

Adapt accordingly—personal scripts need less ceremony, applications need more structure.

## Personal Script Structure

```python
#!/usr/bin/env python3
"""One-line description.

Longer description if needed.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    args = parse_args(argv)
    configure_logging(args.verbose)

    try:
        # Core logic here
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        logger.exception("Unexpected error")
        return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        suggest_on_error=True,  # 3.14+: typo suggestions
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    # Add arguments here
    return parser.parse_args(argv)


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING - (verbosity * 10)
    logging.basicConfig(
        level=max(level, logging.DEBUG),
        format="%(levelname)s: %(message)s",
    )


if __name__ == "__main__":
    sys.exit(main())
```

### New Script Checklist

When creating a new Python script:
- [ ] Add shebang (`#!/usr/bin/env python3` or `#!/usr/bin/env -S uv run` for scripts with dependencies)
- [ ] Add module docstring (one-line description + longer description if needed)
- [ ] Define `main(argv)` returning exit code (0=success, non-zero=error)
- [ ] Add argument parsing with `argparse` (include `suggest_on_error=True` for 3.14+)
- [ ] Add logging configuration with verbosity flag
- [ ] Add `if __name__ == "__main__":` guard calling `sys.exit(main())`
- [ ] Add type hints to all functions
- [ ] Handle `KeyboardInterrupt` (return 130)

## Running Scripts with uv

**No dependencies**: Run directly.
```bash
uv run script.py
```

**With dependencies**: Use inline script metadata (PEP 723).
```python
#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx>=0.27",
#     "rich>=13",
# ]
# ///
"""Script with dependencies."""
import httpx
from rich import print
...
```

Then run with `uv run script.py` or `./script.py` (if executable).

**Ad-hoc dependencies** (no script modification):
```bash
uv run --with httpx --with rich script.py
```

**Ad-hoc heredoc / stdin snippets**:
```bash
uv run --with pypdf python3 - <<'PY'
from pypdf import PdfReader
...
PY
```

When the user provides a `python3 - <<'PY' ... PY` snippet that imports a third-party package, prefer preserving the snippet and wrapping it with `uv run --with <package>` for a one-off fix.

**Specific Python version**:
```bash
uv run --python 3.14 script.py
```

## Missing Dependency Recovery

If execution fails with `ModuleNotFoundError`, do not just report the traceback. Recover by determining which setup the user likely wants:

1. One-off execution:
   ```bash
   uv run --with <package> python3 ...
   ```
2. Repeatable isolated environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install <package>
   ```
3. Install into the currently active interpreter only when the user explicitly wants that:
   ```bash
   python3 -m pip install --user <package>
   ```

For local personal automation on macOS, prefer `uv run --with ...` for quick one-offs and a venv for ongoing work. Global or user-site installs are the fallback, not the default.

## Type Hints

Always use type hints. User has Go background—explicit types are expected.

Prefer direct imports for annotation types in normal code. Use `if TYPE_CHECKING:` only when it solves a real problem, such as an import cycle or a type-only dependency you do not want at runtime.

**Default patterns (3.14+):**
```python
from pathlib import Path

# Built-in generics (no typing import needed)
def process(items: list[str]) -> dict[str, int]: ...

# Union with |
def load(path: str | Path) -> bytes: ...

# Optional = X | None
def find_port(name: str) -> int | None: ...
```

**When to use typing module:**
```python
from typing import TypeAlias, TypeVar, Self, Final
from collections.abc import Callable, Iterator, Sequence, Mapping

# Type aliases for clarity
JsonValue: TypeAlias = dict[str, "JsonValue"] | list["JsonValue"] | str | int | float | bool | None

# TypeVar for generics
T = TypeVar("T")
def first(items: Sequence[T]) -> T | None: ...

# Self for fluent interfaces (3.11+)
class Builder:
    def with_name(self, name: str) -> Self: ...
```

**TypedDict for structured dicts:**
```python
from typing import TypedDict, NotRequired

class Config(TypedDict):
    host: str
    port: int
    timeout: NotRequired[float]  # Optional key
```

**Protocol for duck typing:**
```python
from typing import Protocol

class Readable(Protocol):
    def read(self, n: int = -1) -> bytes: ...
```

## File Operations

Prefer `pathlib.Path` everywhere:

```python
from pathlib import Path

base_dir = Path("data")
path = base_dir / "file.txt"

# Reading/writing
text = path.read_text(encoding="utf-8")
path.write_text(text, encoding="utf-8")
data = path.read_bytes()

# 3.14: copy and move directly
path.copy(base_dir / "file-copy.txt")  # 3.14+
path.move(base_dir / "file-moved.txt")  # 3.14+

# Iterate from a directory, not a file path
for p in base_dir.rglob("*.py"):
    print(p)

# With symlink control (3.13+)
for p in base_dir.glob("**/*.txt", recurse_symlinks=False):
    ...
```

## CLI with argparse

```python
import argparse
from collections.abc import Sequence
from pathlib import Path

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tool description",
        suggest_on_error=True,  # 3.14+
    )

    # Positional
    parser.add_argument("input", type=Path, help="Input file")

    # Optional with default
    parser.add_argument("-o", "--output", type=Path, default=Path("out.txt"))

    # Flag
    parser.add_argument("-f", "--force", action="store_true")

    # Verbosity
    parser.add_argument("-v", "--verbose", action="count", default=0)

    # Choices
    parser.add_argument("--format", choices=["json", "csv"], default="json")

    # Deprecated option (3.13+)
    parser.add_argument("--old-flag", deprecated=True, action="store_true")

    # Subcommands
    subs = parser.add_subparsers(dest="command", required=True)
    run = subs.add_parser("run", help="Run the thing")
    run.add_argument("--dry-run", action="store_true")

    return parser.parse_args(argv)
```

## HTTP Requests

Use `urllib.request` for zero-dependency scripts, `httpx` for anything else:

```python
# Simple GET (stdlib only, no dependencies)
import json
import urllib.request
from typing import Any

def fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)
```

**Prefer httpx** for most cases—add to inline script metadata:
```python
# /// script
# dependencies = ["httpx>=0.27"]
# ///
import httpx
from typing import Any

def fetch(url: str) -> Any:
    with httpx.Client(timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()

# Async
async def fetch_async(url: str) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
```

## JSON Handling

```python
import json
from pathlib import Path

# Load/dump
text = Path("data.json").read_text(encoding="utf-8")
data = json.loads(text)
text = json.dumps(data, indent=2, ensure_ascii=False)

# Files
data = json.loads(Path("data.json").read_text(encoding="utf-8"))
Path("out.json").write_text(
    json.dumps(data, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

# Custom encoding
class CustomEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, Path):
            return str(o)
        return super().default(o)
```

## Error Handling

```python
# Handle expected failures close to the source.
try:
    data = load_config(path)
except FileNotFoundError:
    logger.error("Config not found: %s", path)
    return 1
except json.JSONDecodeError as e:
    logger.error("Invalid JSON in %s at line %d: %s", path, e.lineno, e.msg)
    return 1
except OSError as e:
    logger.error("Could not read %s: %s", path, e)
    return 1

# Group related exception types when the handling is the same.
try:
    port = int(raw_port)
except (TypeError, ValueError) as e:
    logger.error("Invalid port value %r: %s", raw_port, e)
    return 1

# Custom exceptions
class AppError(Exception):
    """Base for application errors."""

class ConfigError(AppError):
    """Configuration error."""
```

## Dataclasses for Structured Data

Prefer dataclasses over plain classes or dicts:

```python
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Self

class ConfigError(Exception):
    """Configuration file is missing, invalid, or incomplete."""


@dataclass
class Config:
    host: str
    port: int = 8080
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> Self:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as e:
            raise ConfigError(f"Could not read config file: {path}") from e
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in {path} at line {e.lineno}") from e

        if not isinstance(data, dict):
            raise ConfigError(f"Expected a JSON object in {path}")

        try:
            return cls(**data)
        except TypeError as e:
            raise ConfigError(f"Invalid config shape in {path}: {e}") from e

@dataclass(frozen=True)  # Immutable
class Point:
    x: float
    y: float
```

## Compression (3.14+)

```python
# 3.14+: zstd in stdlib
from compression import zstd

data = b"hello\n"

# One-shot
compressed = zstd.compress(data)
original = zstd.decompress(compressed)

# File operations
with zstd.open("data.zst", "wt", encoding="utf-8") as f:
    f.write("hello\n")
```

## Key-Value Storage

```python
# 3.13+: `dbm.open()` uses `dbm.sqlite3` for new files when available
import dbm

with dbm.open("cache", "c") as db:
    db["key"] = b"value"
    value = db.get("key", b"default")
```

## Version-Specific Features

This skill includes a comprehensive feature reference for Python 3.13 and 3.14.
See [references/python_features_313_314.md](references/python_features_313_314.md) for the complete feature list.

Quick version check:
```python
import sys

if sys.version_info >= (3, 14):
    from compression import zstd
    # Use Path.copy(), Path.move()
    # Use argparse suggest_on_error
    # Python 3.14 also allows `except ValueError, TypeError:`
    # Prefer `except (ValueError, TypeError):` for readability.
    # Do not add `from __future__ import annotations` in new 3.14-only code.

if sys.version_info >= (3, 13):
    # `dbm.open()` may use `dbm.sqlite3` for new files when available
    # Use Path.glob(recurse_symlinks=)
    # Use argparse deprecated=
```

## Larger Application Adaptations

When in a larger application context:

1. **Structure**: Follow `src/` layout, separate concerns into modules
2. **Dependencies**: Use `pyproject.toml` with `uv`:
   ```bash
   uv init myproject        # New project
   uv add httpx rich        # Add dependencies
   uv add --dev pytest ruff # Dev dependencies
   uv sync                  # Install all deps
   uv run pytest            # Run with project env
   ```
3. **Lock file**: Commit `uv.lock` for reproducible builds
4. **Testing**: `uv run pytest`, aim for meaningful coverage
5. **Linting**: `uv run ruff check .` and `uv run ruff format .`
6. **CI**: Use `uv` in GitHub Actions:
   ```yaml
   - uses: astral-sh/setup-uv@v4
   - run: uv sync
   - run: uv run pytest
   ```
7. **Logging**: Use structured logging, configure at application boundary
8. **Config**: Use environment variables or config files, not hardcoded values
