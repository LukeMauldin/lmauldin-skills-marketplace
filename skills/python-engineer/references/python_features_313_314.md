# Python 3.13, and 3.14 Features for LLM Agents

> Reference guide for LLM agents writing CLI scripts (200-400 lines) involving HTTP/JSON APIs, file I/O, and command-line interfaces.

---

- Multiline editing with history preservation
- Color support for prompts and tracebacks (enabled by default)
- Direct REPL commands: `help`, `exit`, `quit` (no parentheses needed)
- `F1` for interactive help, `F2` for history browsing, `F3` for paste mode
- Disable with `PYTHON_BASIC_REPL` environment variable
- Disable colors with `PYTHON_COLORS=0` or `NO_COLOR`

### Improved Error Messages

- Tracebacks highlighted in color by default
- Suggests correct keyword arguments when incorrect ones passed
- Detects script name collisions with standard library modules
- Better error messages for missing imports

### Free-Threaded Mode (Experimental, PEP 703)

- Experimental build that disables the GIL
- Enable at runtime: `PYTHON_GIL=0` or `-X gil=0`
- Check status: `sys._is_gil_enabled()`
- Check build: `python -VV` shows "experimental free-threading build"

### JIT Compiler (Experimental, PEP 744)

- Preliminary JIT using copy-and-patch technique
- Disabled by default, foundation for future performance gains

### `locals()` Semantics (PEP 667)

- Now has defined behavior when mutating returned mapping
- Debuggers can more reliably update local variables
- Returns independent snapshots in optimized scopes (functions, comprehensions)

### Standard Library Changes

**`argparse` Improvements:**
- `deprecated` parameter for options, arguments, and subcommands
- Clearer deprecation warnings in help output

**`dbm` Module:**
- New `dbm.sqlite3` backend (`dbm.open()` can use it for new files when available)
- No external dependencies needed for basic key-value storage

**`base64` Module:**
- New `z85encode()` and `z85decode()` for Z85 encoding

**`pathlib` Improvements:**
- `Path.glob()` and `Path.rglob()` gain `recurse_symlinks` parameter
- Pattern parameter accepts path-like objects
- `OSError` exceptions during scanning now suppressed
- `follow_symlinks` parameter added to `owner()`, `group()`, `chmod()`

**`shutil` Improvements:**
- Many bug fixes for recursive operations and error handling
- Better symlink handling

**`zipfile.Path` Improvements:**
- Better directory handling
- Quality-of-life improvements for traversing zip files

**Removed Modules (PEP 594):**
- `aifc`, `audioop`, `chunk`, `cgi`, `cgitb`, `crypt`
- `imghdr`, `mailcap`, `msilib`, `nis`, `nntplib`
- `ossaudiodev`, `pipes`, `sndhdr`, `spwd`, `sunau`
- `telnetlib`, `uu`, `xdrlib`, `lib2to3`

### Typing Improvements

- `typing.TypeIs` for type narrowing when the narrowed type is a subtype of the input type
- `typing.TypeGuard` is still needed for narrowing patterns that are not subtype-based
- `typing.ReadOnly` for read-only items in `TypedDict`
- `@typing.deprecated` decorator for deprecation in type system
- Type parameter defaults: `class Foo[T = int]:`

### Platform Changes

- Minimum macOS version: 10.13 (High Sierra)
- WASI is Tier 2 supported
- Android is Tier 3 supported

---

## Python 3.14 (Released October 2025)

### Template Strings (PEP 750)

- New `t"..."` prefix creates `Template` objects instead of strings
- Captures both static parts and interpolated expressions
- Enables custom string processing and safer substitution patterns
- Similar syntax to f-strings but doesn't immediately produce a string

### Deferred Annotation Evaluation (PEP 649)

- Annotations no longer evaluated eagerly at definition time
- Stored in special `__annotate__` functions, evaluated on demand
- Forward references work without `from __future__ import annotations`
- New 3.14-only code should not add `from __future__ import annotations` by default
- New `annotationlib` module for introspection
- Better performance for code with many annotations

### Subinterpreters in stdlib (PEP 734)

- New `concurrent.interpreters` module
- Each interpreter has its own GIL
- Enables CSP-style concurrency patterns
- `concurrent.futures.InterpreterPoolExecutor` for familiar API

### Free-Threaded Python Officially Supported (PEP 779)

- No longer experimental, now officially maintained
- Still opt-in (GIL enabled by default)
- Build with `--disable-gil` flag
- Better ecosystem support than 3.13

### Zstandard Compression (PEP 784)

- New `compression.zstd` module in stdlib
- No external dependencies for zstd compression
- `compression.zstd.open()` for file operations
- `compression.zstd.compress()` / `decompress()` for one-shot operations
- `ZstdCompressor` / `ZstdDecompressor` for streaming
- Dictionary training support
- `shutil.make_archive()` supports `zstdtar` format
- `zipfile` supports `ZIP_ZSTANDARD` compression

### REPL Improvements

- Syntax highlighting while typing (keywords, strings, comments colored)
- Colors in Python debugger (`pdb`) as well
- Disable with `PYTHON_COLORS=0`

### CLI Color Output

- `argparse` displays colorful help messages
- `calendar` module highlights current day
- `json` module pretty-prints with colors: `python -m json.tool`
- `unittest` shows colored pass/fail output

### `argparse` Improvements

- `suggest_on_error=True` parameter suggests corrections for typos
- Example: typing "scisors" suggests "scissors"
- Color in help output

### `pathlib` Improvements

- `Path.copy()` method for copying files
- `Path.move()` method for moving/renaming files
- No longer need `shutil` for basic file operations

### Exception Handling (PEP 758)

- `except` and `except*` expressions can omit parentheses
- `except ValueError, TypeError:` now valid (was `except (ValueError, TypeError):`)

### `uuid` Module

- UUID versions 6-8 now supported
- Generation of versions 3-5 up to 40% faster

### Debugging Improvements

- `pdb` supports remote attaching to running processes
- New CLI to inspect running asyncio tasks
- External debugger interface (PEP 768) for zero-overhead debugging

### `asyncio` Improvements

- Significantly improved introspection capabilities
- Better `TaskGroup` handling for nested cancellations
- Cancellation count preserved correctly

### Control Flow in `finally` Blocks

- `return`, `break`, `continue` in `finally` blocks now emit `SyntaxWarning`
- Previously could silently suppress exceptions

### Performance

- Incremental garbage collection (smoother latency)
- New tail-call interpreter option (3-5% faster with Clang 19+)
- JIT compiler included in official builds (experimental)

### `shutil` Changes

- Default tar extraction filter is now `'data'` (safer)
- `zstdtar` format support

### Platform/Build Changes

- No more PGP signatures (use Sigstore instead)
- New Windows install manager
- Emscripten Tier 3 supported (PEP 776)
- Official Android binary releases

---

## Quick Reference: What to Use When

### File Operations
| Task | Python 3.12 | Python 3.13 | Python 3.14 |
|------|-------------|-------------|-------------|
| Walk directories | `Path.walk()` | `Path.walk()` | `Path.walk()` |
| Copy file | `shutil.copy()` | `shutil.copy()` | `Path.copy()` ✨ |
| Move file | `shutil.move()` | `shutil.move()` | `Path.move()` ✨ |
| Glob with symlinks | Manual handling | `recurse_symlinks=True` | `recurse_symlinks=True` |

### Compression
| Format | Python 3.12 | Python 3.13 | Python 3.14 |
|--------|-------------|-------------|-------------|
| gzip | `gzip` | `gzip` | `gzip` |
| bz2 | `bz2` | `bz2` | `bz2` |
| lzma/xz | `lzma` | `lzma` | `lzma` |
| zstd | Third-party | Third-party | `compression.zstd` ✨ |

### CLI Argument Parsing
| Feature | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|-------------|-------------|-------------|
| Basic parsing | `argparse` | `argparse` | `argparse` |
| Deprecate options | Manual | `deprecated=True` ✨ | `deprecated=True` |
| Typo suggestions | No | No | `suggest_on_error=True` ✨ |
| Color help | No | No | Automatic ✨ |

### Key-Value Storage
| Need | Python 3.12 | Python 3.13+ |
|------|-------------|--------------|
| Store Python objects | `shelve` (dbm backend varies) | `shelve` (dbm backend varies) |
| Store bytes values by key | `dbm` (backend varies) | `dbm` (`dbm.sqlite3` for new files when available) ✨ |

### String Formatting
| Feature | Python 3.12+ |
|---------|--------------|
| Backslash in f-string | ✅ Works |
| Nested quotes | ✅ Works |
| Multiline expressions | ✅ Works |

---

## Removed/Deprecated: Don't Use These

### Removed in 3.12+
- `distutils` → use `setuptools` or `build`
- `imp` → use `importlib`
- `asynchat`, `asyncore` → use `asyncio`

### Removed in 3.13+
- `cgi`, `cgitb` → use web frameworks or manual parsing
- `telnetlib` → use `telnetlib3` or `asyncio` sockets
- `uu` → use `base64`
- `imghdr` → use `filetype` or `python-magic`
- `lib2to3` → code conversion no longer needed

### Deprecated (still works but avoid)
- `datetime.utcnow()` → use `datetime.now(timezone.utc)`
- `datetime.utcfromtimestamp()` → use `datetime.fromtimestamp(ts, timezone.utc)`

---

## Version Detection

```python
import sys

# Check Python version
if sys.version_info >= (3, 14):
    from compression import zstd
elif sys.version_info >= (3, 13):
    # `dbm.open()` may use `dbm.sqlite3` for new files when available
    pass
    
# Check for free-threading
if hasattr(sys, '_is_gil_enabled'):
    gil_disabled = not sys._is_gil_enabled()
```

---

## Environment Variables Reference

| Variable | Purpose | Version |
|----------|---------|---------|
| `PYTHON_COLORS=0` | Disable color output | 3.13+ |
| `NO_COLOR` | Standard no-color variable | 3.13+ |
| `PYTHON_BASIC_REPL` | Use old REPL | 3.13+ |
| `PYTHON_GIL=0` | Disable GIL (free-threaded build) | 3.13+ |
