#!/usr/bin/env python3
"""Analyze collected macOS memory-pressure metrics and generate a report."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_PAGE_SIZE = 16384  # Safe fallback on Apple Silicon.
PAGE_SIZE = DEFAULT_PAGE_SIZE

VM_STAT_COLUMNS = [
    "free",
    "active",
    "specul",
    "inactive",
    "throttle",
    "wired",
    "prgable",
    "faults",
    "copy",
    "zerofill",
    "reactive",
    "purged",
    "file_backed",
    "anonymous",
    "compressed",
    "compressor",
    "decompressions",
    "compressions",
    "pageins",
    "pageouts",
    "swapins",
    "swapouts",
]

TOP_ROW_RE = re.compile(
    r"^\s*(?P<pid>\d+)\s+"
    r"(?P<command>.+?)\s+"
    r"(?P<cpu>-?\d+(?:\.\d+)?)\s+"
    r"(?P<time>\S+)\s+"
    r"(?P<th>\d+)\s+"
    r"(?P<wq>\d+)\s+"
    r"(?P<ports>\d+)\s+"
    r"(?P<mem>\S+)\s+"
    r"(?P<purg>\S+)\s+"
    r"(?P<cmprs>\S+)\s+"
)

DELTA_INTERVAL_SECONDS = 5
MIN_CONFIDENT_INTERVALS = 12
TOP_MOVER_MIN_DELTA_MB = 200.0


def read_text(filepath: Path) -> str:
    """Read UTF-8 text with replacement; return empty string for missing files."""
    if not filepath.exists():
        return ""
    return filepath.read_text(encoding="utf-8", errors="replace")


def detect_page_size(data_dir: Path) -> int:
    """Detect page size from collected files, then system defaults."""
    candidates = [
        data_dir / "vm_stat.txt",
        data_dir / "vm_stat_deltas.txt",
        data_dir / "memory_pressure.txt",
    ]
    vm_stat_matcher = re.compile(r"page size of (\d+) bytes", re.IGNORECASE)
    mem_pressure_matcher = re.compile(r"page size of (\d+)\)", re.IGNORECASE)

    for candidate in candidates:
        content = read_text(candidate)
        if not content:
            continue
        vm_match = vm_stat_matcher.search(content)
        if vm_match:
            size = int(vm_match.group(1))
            if size > 0:
                return size
        mem_match = mem_pressure_matcher.search(content)
        if mem_match:
            size = int(mem_match.group(1))
            if size > 0:
                return size

    try:
        sysconf_size = os.sysconf("SC_PAGE_SIZE")
        if isinstance(sysconf_size, int) and sysconf_size > 0:
            return sysconf_size
    except (AttributeError, OSError, ValueError):
        pass

    return DEFAULT_PAGE_SIZE


def size_unit_to_mb(value: float, unit: str) -> float:
    """Convert a numeric size with unit suffix into MB."""
    unit_normalized = unit.upper()
    multipliers = {
        "T": 1024.0 * 1024.0,
        "G": 1024.0,
        "M": 1.0,
        "K": 1.0 / 1024.0,
        "B": 1.0 / (1024.0 * 1024.0),
    }
    return value * multipliers.get(unit_normalized, 0.0)


def parse_size_to_mb(token: str) -> float:
    """Parse values like `2G`, `6144.00M`, `6368K`, `0B` into MB."""
    cleaned = token.strip().rstrip("+").replace(",", "")
    if cleaned in {"", "0", "0B"}:
        return 0.0

    match = re.fullmatch(r"(\d+(?:\.\d+)?)([TGMKB])", cleaned, re.IGNORECASE)
    if not match:
        # Bare numbers are treated as bytes for defensive compatibility.
        try:
            return float(cleaned) / (1024.0 * 1024.0)
        except ValueError:
            return 0.0

    return size_unit_to_mb(float(match.group(1)), match.group(2))


def parse_vm_count(token: str) -> int | None:
    """Parse vm_stat counters, handling compact `K` suffix rows."""
    cleaned = token.strip().rstrip(".")
    match = re.fullmatch(r"(\d+)([KMG])?", cleaned, re.IGNORECASE)
    if not match:
        return None

    value = int(match.group(1))
    suffix = (match.group(2) or "").upper()
    if suffix == "K":
        return value * 1000
    if suffix == "M":
        return value * 1_000_000
    if suffix == "G":
        return value * 1_000_000_000
    return value


def load_json_file(filepath: Path) -> dict[str, Any] | None:
    """Load a JSON object from disk if available and valid."""
    if not filepath.exists():
        return None
    try:
        parsed = json.loads(filepath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_previous_summary(previous_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize previous analysis data across old/new schema versions."""
    run_summary = previous_data.get("run_summary")
    if isinstance(run_summary, dict):
        return run_summary

    swap = previous_data.get("swap")
    free_memory = previous_data.get("free_memory")
    reactivation = previous_data.get("reactivation")
    return {
        "timestamp": previous_data.get("timestamp"),
        "score": previous_data.get("score"),
        "level": previous_data.get("level"),
        "swap_used_mb": swap.get("used_mb") if isinstance(swap, dict) else None,
        "swap_used_pct": swap.get("used_pct") if isinstance(swap, dict) else None,
        "avg_free_mb": free_memory.get("avg_mb") if isinstance(free_memory, dict) else None,
        "thrashing_count": reactivation.get("thrashing_count") if isinstance(reactivation, dict) else None,
        "intervals": (
            free_memory.get("total_intervals")
            if isinstance(free_memory, dict)
            else None
        ),
    }


def to_float(value: Any) -> float | None:
    """Convert values to float when possible."""
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compare_with_previous_run(
    current_summary: dict[str, Any], previous_data: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Build a compact comparison against a previous run summary."""
    if not previous_data:
        return None

    previous_summary = extract_previous_summary(previous_data)

    comparison: dict[str, Any] = {
        "previous_timestamp": previous_summary.get("timestamp"),
        "previous_level": previous_summary.get("level"),
        "current_level": current_summary.get("level"),
    }

    metric_keys = [
        "score",
        "swap_used_mb",
        "swap_used_pct",
        "avg_free_mb",
        "thrashing_count",
        "intervals",
    ]
    has_any_delta = False
    for key in metric_keys:
        current_value = to_float(current_summary.get(key))
        previous_value = to_float(previous_summary.get(key))
        comparison[f"current_{key}"] = current_summary.get(key)
        comparison[f"previous_{key}"] = previous_summary.get(key)
        if current_value is None or previous_value is None:
            comparison[f"delta_{key}"] = None
            continue

        delta = current_value - previous_value
        comparison[f"delta_{key}"] = delta
        if abs(delta) > 1e-9:
            has_any_delta = True

    return comparison if has_any_delta else None

# ============================================================
# Parsing Functions
# ============================================================

def parse_memory_pressure(filepath: Path) -> dict[str, int]:
    """Parse output of `memory_pressure` command."""
    data: dict[str, int] = {}
    content = read_text(filepath)
    if not content:
        return data

    patterns = {
        "total_bytes": r"system has (\d+) \(",
        "total_pages": r"\((\d+) pages",
        "pages_free": r"Pages free:\s+(\d+)",
        "pages_purgeable": r"Pages purgeable:\s+(\d+)",
        "pages_purged": r"Pages purged:\s+(\d+)",
        "swapins": r"Swapins:\s+(\d+)",
        "swapouts": r"Swapouts:\s+(\d+)",
        "pages_active": r"Pages active:\s+(\d+)",
        "pages_inactive": r"Pages inactive:\s+(\d+)",
        "pages_speculative": r"Pages speculative:\s+(\d+)",
        "pages_wired": r"Pages wired down:\s+(\d+)",
        "compressor_pages_used": r"Pages used by compressor:\s+(\d+)",
        "pages_decompressed": r"Pages decompressed:\s+(\d+)",
        "pages_compressed": r"Pages compressed:\s+(\d+)",
        "pageins": r"Pageins:\s+(\d+)",
        "pageouts": r"Pageouts:\s+(\d+)",
        "free_percentage": r"free percentage:\s+(\d+)%",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            data[key] = int(match.group(1))

    return data


def parse_vm_stat(filepath: Path) -> dict[str, int]:
    """Parse output of `vm_stat` (single snapshot)."""
    data: dict[str, int] = {}
    content = read_text(filepath)
    if not content:
        return data

    patterns = {
        "pages_free": r"Pages free:\s+(\d+)",
        "pages_active": r"Pages active:\s+(\d+)",
        "pages_inactive": r"Pages inactive:\s+(\d+)",
        "pages_speculative": r"Pages speculative:\s+(\d+)",
        "pages_wired": r"Pages wired down:\s+(\d+)",
        "pages_purgeable": r"Pages purgeable:\s+(\d+)",
        "translation_faults": r'"Translation faults":\s+(\d+)',
        "copy_on_write": r"Pages copy-on-write:\s+(\d+)",
        "zero_filled": r"Pages zero filled:\s+(\d+)",
        "reactivated": r"Pages reactivated:\s+(\d+)",
        "purged": r"Pages purged:\s+(\d+)",
        "file_backed": r"File-backed pages:\s+(\d+)",
        "anonymous": r"Anonymous pages:\s+(\d+)",
        "stored_in_compressor": r"Pages stored in compressor:\s+(\d+)",
        "occupied_by_compressor": r"Pages occupied by compressor:\s+(\d+)",
        "decompressions": r"Decompressions:\s+(\d+)",
        "compressions": r"Compressions:\s+(\d+)",
        "pageins": r"Pageins:\s+(\d+)",
        "pageouts": r"Pageouts:\s+(\d+)",
        "swapins": r"Swapins:\s+(\d+)",
        "swapouts": r"Swapouts:\s+(\d+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, content)
        if match:
            data[key] = int(match.group(1))

    return data


def parse_swap(filepath: Path) -> dict[str, float]:
    """Parse output of `sysctl vm.swapusage`."""
    data: dict[str, float] = {}
    content = read_text(filepath)
    if not content:
        return data

    for field in ("total", "used", "free"):
        match = re.search(
            rf"{field}\s*=\s*([\d.]+)\s*([TGMK])",
            content,
            re.IGNORECASE,
        )
        if match:
            data[f"{field}_mb"] = size_unit_to_mb(float(match.group(1)), match.group(2))

    return data


def parse_top_output(filepath: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse output of `top -l 1 -o mem -n 25`."""
    processes: list[dict[str, Any]] = []
    content = read_text(filepath)
    if not content:
        return processes, {}

    lines = content.splitlines()

    # Extract summary info
    summary: dict[str, Any] = {}
    for line in lines:
        if line.startswith("Load Avg:"):
            match = re.search(r"Load Avg:\s+([\d.]+),\s+([\d.]+),\s+([\d.]+)", line)
            if match:
                summary["load_avg"] = [float(match.group(i)) for i in range(1, 4)]
        elif line.startswith("PhysMem:"):
            match = re.search(
                r"([\d.]+)G used.*?(\d+)M wired.*?(\d+)M compressor.*?(\d+)M unused",
                line,
            )
            if not match:
                match = re.search(r"([\d.]+)G used.*?(\d+)M unused", line)
            if match:
                summary["phys_used_gb"] = float(match.group(1))
        elif line.startswith("Processes:"):
            match = re.search(r"(\d+) total.*?(\d+) threads", line)
            if match:
                summary["process_count"] = int(match.group(1))
                summary["thread_count"] = int(match.group(2))

    # Parse process lines
    in_processes = False
    for line in lines:
        if line.strip().startswith("PID"):
            in_processes = True
            continue
        if not in_processes:
            continue

        match = TOP_ROW_RE.match(line)
        if not match:
            continue

        try:
            pid = int(match.group("pid"))
        except ValueError:
            continue

        command = match.group("command").strip()
        mem_mb = parse_mem_value(match.group("mem"))
        cmprs_mb = parse_mem_value(match.group("cmprs"))

        processes.append({
            "pid": pid,
            "command": command,
            "mem_mb": mem_mb,
            "cmprs_mb": cmprs_mb,
            "raw_line": line.strip(),
        })

    return processes, summary


def parse_mem_value(s: str) -> float:
    """Convert memory string like '3001M', '2G', '51K', '0B' to MB."""
    return parse_size_to_mb(s)


def parse_vm_stat_deltas(filepath: Path) -> list[dict[str, int]]:
    """Parse output of `vm_stat 5` (periodic deltas)."""
    deltas: list[dict[str, int]] = []
    content = read_text(filepath)
    if not content:
        return deltas

    expect_data_rows = False
    row_index_in_batch = 0

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()
        if lower.startswith("usage:") or "not found" in lower or "illegal option" in lower:
            # Invalid command output from collection step; ignore.
            continue
        if stripped.startswith("Mach"):
            continue
        if stripped.startswith("free"):
            expect_data_rows = True
            row_index_in_batch = 0
            continue
        if not expect_data_rows:
            continue

        parts = stripped.split()
        if len(parts) < len(VM_STAT_COLUMNS):
            continue

        has_suffix = any(
            bool(re.search(r"[A-Za-z]$", token))
            for token in parts[: len(VM_STAT_COLUMNS)]
        )
        if row_index_in_batch == 0 and has_suffix:
            # First line after each header is cumulative, not a delta row.
            row_index_in_batch += 1
            continue

        row: dict[str, int] = {}
        valid_row = True
        for col, token in zip(VM_STAT_COLUMNS, parts[: len(VM_STAT_COLUMNS)]):
            value = parse_vm_count(token)
            if value is None:
                valid_row = False
                break
            row[col] = value

        if not valid_row or not any(row.values()):
            continue

        deltas.append(row)
        row_index_in_batch += 1

    return deltas


# ============================================================
# Analysis Functions
# ============================================================

def pages_to_mb(pages: float) -> float:
    return pages * PAGE_SIZE / 1024 / 1024


def pages_to_gb(pages: float) -> float:
    return pages * PAGE_SIZE / 1024 / 1024 / 1024


def analyze_capacity(mem_pressure: dict[str, int], vm_stat_data: dict[str, int]) -> dict[str, float]:
    """Analyze sustained memory occupancy indicators."""
    total_pages = mem_pressure.get("total_pages", 0)
    if total_pages <= 0 and mem_pressure.get("total_bytes", 0) > 0:
        total_pages = int(mem_pressure["total_bytes"] // PAGE_SIZE)

    occupied_pages = vm_stat_data.get("occupied_by_compressor", 0)
    occupied_mb = pages_to_mb(occupied_pages)
    occupied_pct = (occupied_pages / total_pages * 100.0) if total_pages > 0 else 0.0

    return {
        "compressor_occupied_pages": float(occupied_pages),
        "compressor_occupied_mb": occupied_mb,
        "compressor_occupied_pct_of_ram": occupied_pct,
    }


def analyze_swap(mem_pressure, vm_stat, swap_info, deltas):
    """Analyze swap activity."""
    results = {}
    
    if swap_info:
        results['total_mb'] = swap_info.get('total_mb', 0)
        results['used_mb'] = swap_info.get('used_mb', 0)
        results['free_mb'] = swap_info.get('free_mb', 0)
        if results['total_mb'] > 0:
            results['used_pct'] = results['used_mb'] / results['total_mb'] * 100
    
    if mem_pressure:
        results['cumulative_swapins'] = mem_pressure.get('swapins', 0)
        results['cumulative_swapouts'] = mem_pressure.get('swapouts', 0)
    
    if deltas:
        swapouts = [r['swapouts'] for r in deltas]
        swapins = [r['swapins'] for r in deltas]
        results['delta_total_swapouts'] = sum(swapouts)
        results['delta_total_swapins'] = sum(swapins)
        results['intervals_with_swapouts'] = sum(1 for s in swapouts if s > 0)
        results['intervals_with_swapins'] = sum(1 for s in swapins if s > 0)
        results['max_swapout_pages'] = max(swapouts) if swapouts else 0
        results['total_intervals'] = len(deltas)
    
    return results


def analyze_compression(deltas):
    """Analyze compression activity from deltas."""
    if not deltas:
        return {}
    
    compressions = [r['compressions'] for r in deltas]
    decompressions = [r['decompressions'] for r in deltas]
    compressor = [r['compressor'] for r in deltas]
    compressed = [r['compressed'] for r in deltas]
    
    results = {
        'total_compressions': sum(compressions),
        'total_decompressions': sum(decompressions),
        'avg_compressions_per_interval': sum(compressions) / len(deltas),
        'avg_decompressions_per_interval': sum(decompressions) / len(deltas),
        'max_compressions': max(compressions),
        'max_decompressions': max(decompressions),
        'heavy_compression_intervals': sum(1 for c in compressions if c > 50000),
        'compressor_mb_range': (pages_to_mb(min(compressor)), pages_to_mb(max(compressor))),
        'compressed_mb_range': (pages_to_mb(min(compressed)), pages_to_mb(max(compressed))),
        'total_intervals': len(deltas),
    }
    
    # Compression ratios at checkpoints
    ratios = []
    for i in [0, len(deltas)//4, len(deltas)//2, 3*len(deltas)//4, -1]:
        if compressed[i] > 0 and compressor[i] > 0:
            ratios.append(compressed[i] / compressor[i])
    results['compression_ratios'] = ratios
    results['avg_compression_ratio'] = sum(ratios) / len(ratios) if ratios else 0
    
    return results


def analyze_reactivations(deltas):
    """Analyze page reactivations (thrashing indicator)."""
    if not deltas:
        return {}
    
    reactivations = [r['reactive'] for r in deltas]
    compressions = [r['compressions'] for r in deltas]
    
    # Find thrashing episodes
    thrashing_episodes = []
    for i, r in enumerate(deltas):
        if r['reactive'] > 50000 and r['compressions'] > 50000:
            thrashing_episodes.append({
                'interval': i,
                'time_s': i * DELTA_INTERVAL_SECONDS,
                'reactivations': r['reactive'],
                'compressions': r['compressions'],
                'decompressions': r['decompressions'],
                'swapouts': r['swapouts'],
            })
    
    return {
        'total_reactivations': sum(reactivations),
        'avg_per_interval': sum(reactivations) / len(deltas),
        'max_reactivations': max(reactivations),
        'heavy_intervals': sum(1 for r in reactivations if r > 50000),
        'thrashing_episodes': thrashing_episodes,
        'thrashing_count': len(thrashing_episodes),
        'total_intervals': len(deltas),
    }


def analyze_free_memory(deltas):
    """Analyze free memory over time."""
    if not deltas:
        return {}
    
    free_mb = [pages_to_mb(r['free']) for r in deltas]
    sorted_free = sorted(free_mb)
    
    return {
        'min_mb': min(free_mb),
        'max_mb': max(free_mb),
        'avg_mb': sum(free_mb) / len(free_mb),
        'median_mb': sorted_free[len(sorted_free) // 2],
        'below_100mb': sum(1 for f in free_mb if f < 100),
        'below_500mb': sum(1 for f in free_mb if f < 500),
        'above_1gb': sum(1 for f in free_mb if f > 1024),
        'total_intervals': len(deltas),
    }


def analyze_phases(deltas, window_seconds=60):
    """Classify time windows into calm/elevated/storm phases."""
    if not deltas:
        return []
    
    window_size = max(window_seconds // DELTA_INTERVAL_SECONDS, 1)
    phases = []
    
    for w in range(0, len(deltas), window_size):
        chunk = deltas[w:w + window_size]
        if len(chunk) < 2:
            continue
        
        w_swapouts = sum(r['swapouts'] for r in chunk)
        w_comp = sum(r['compressions'] for r in chunk)
        w_react = sum(r['reactive'] for r in chunk)
        w_free_avg = sum(pages_to_mb(r['free']) for r in chunk) / len(chunk)
        
        if w_swapouts > 1000 or w_react > 200000 or w_comp > 300000:
            phase = "STORM"
        elif w_react > 50000 or w_comp > 100000:
            phase = "ELEVATED"
        else:
            phase = "CALM"
        
        phases.append({
            'start_s': w * DELTA_INTERVAL_SECONDS,
            'end_s': (w + len(chunk)) * DELTA_INTERVAL_SECONDS,
            'phase': phase,
            'avg_free_mb': w_free_avg,
            'reactivations': w_react,
            'compressions': w_comp,
            'swapouts': w_swapouts,
        })
    
    return phases


def group_processes(processes):
    """Group processes by application."""
    app_groups = {}
    
    app_patterns = [
        (r'Google Chrome|Chrome Helper', 'Google Chrome'),
        (r'Cursor Helper|Cursor$', 'Cursor IDE'),
        (r'Code Helper|Code$', 'VS Code'),
        (r'Slack Helper|Slack$', 'Slack'),
        (r'Obsidian', 'Obsidian'),
        (r'rust-analyzer', 'rust-analyzer'),
        (r'gopls', 'gopls (Go LSP)'),
        (r'tsserver|typescript', 'TypeScript LSP'),
        (r'com\.apple\.Virtua', 'Apple Virtualization (VM)'),
        (r'WindowServer', 'WindowServer (system)'),
        (r'kernel_task', 'kernel_task (system)'),
        (r'iTerm', 'iTerm2'),
        (r'Terminal', 'Terminal'),
        (r'Claude', 'Claude (desktop/code)'),
        (r'Docker', 'Docker'),
        (r'OrbStack', 'OrbStack'),
        (r'node$', 'Node.js'),
        (r'Safari', 'Safari'),
        (r'Firefox', 'Firefox'),
        (r'Arc Helper|Arc$', 'Arc Browser'),
        (r'Brave Helper|Brave$', 'Brave Browser'),
        (r'Xcode', 'Xcode'),
        (r'sourcekit-lsp|SourceKit', 'SourceKit LSP'),
        (r'clangd', 'clangd (C++ LSP)'),
        (r'pylsp|pyright|python.*language', 'Python LSP'),
    ]
    
    for proc in processes:
        app_name = proc['command']
        for pattern, name in app_patterns:
            if re.search(pattern, proc['command'], re.IGNORECASE):
                app_name = name
                break
        
        if app_name not in app_groups:
            app_groups[app_name] = {'mem_mb': 0, 'cmprs_mb': 0, 'processes': 0, 'pids': []}
        app_groups[app_name]['mem_mb'] += proc['mem_mb']
        app_groups[app_name]['cmprs_mb'] += proc['cmprs_mb']
        app_groups[app_name]['processes'] += 1
        app_groups[app_name]['pids'].append(proc['pid'])
    
    return app_groups


def app_total_demand_mb(app_data: dict[str, Any]) -> float:
    """Compute resident+compressed memory demand for one app group."""
    return float(app_data.get("mem_mb", 0.0)) + float(app_data.get("cmprs_mb", 0.0))


def compute_top_movers(
    app_groups_start: dict[str, dict[str, Any]],
    app_groups_end: dict[str, dict[str, Any]],
    min_delta_mb: float = TOP_MOVER_MIN_DELTA_MB,
    limit: int = 7,
) -> list[dict[str, Any]]:
    """Compare start/end app groups and return largest demand movers."""
    if not app_groups_start or not app_groups_end:
        return []

    movers: list[dict[str, Any]] = []
    for app in sorted(set(app_groups_start) | set(app_groups_end)):
        start = app_groups_start.get(app, {})
        end = app_groups_end.get(app, {})
        start_demand = app_total_demand_mb(start)
        end_demand = app_total_demand_mb(end)
        delta = end_demand - start_demand
        if abs(delta) < min_delta_mb:
            continue
        movers.append(
            {
                "app": app,
                "start_mb": start_demand,
                "end_mb": end_demand,
                "delta_mb": delta,
                "start_processes": int(start.get("processes", 0)),
                "end_processes": int(end.get("processes", 0)),
            }
        )

    movers.sort(key=lambda item: abs(float(item["delta_mb"])), reverse=True)
    return movers[:limit]


def calculate_pressure_score(
    swap_analysis,
    reactivation_analysis,
    free_analysis,
    compression_analysis,
    capacity_analysis,
):
    """Calculate overall pressure score 0-12."""
    score = 0
    reasons = []
    
    # Swap activity (0-3 points)
    if swap_analysis.get('total_intervals', 0) > 0:
        swap_pct = swap_analysis.get('intervals_with_swapouts', 0) / swap_analysis['total_intervals']
        if swap_pct > 0.3:
            score += 3
            reasons.append(f"Swap writes in {swap_pct*100:.0f}% of intervals")
        elif swap_pct > 0.05:
            score += 2
            reasons.append(f"Swap writes in {swap_pct*100:.0f}% of intervals")
        elif swap_analysis.get('delta_total_swapouts', 0) > 0:
            score += 1
            reasons.append("Some swap write activity detected")
    
    # Sustained swap occupancy (0-2 points)
    swap_used_pct = swap_analysis.get("used_pct", 0)
    if swap_used_pct > 90:
        score += 2
        reasons.append(
            f"Swap persistently high ({swap_used_pct:.0f}% full; "
            f"{swap_analysis.get('used_mb', 0):.0f}/{swap_analysis.get('total_mb', 0):.0f} MB)"
        )
    elif swap_used_pct > 75:
        score += 1
        reasons.append(
            f"Swap occupancy elevated ({swap_used_pct:.0f}% full; "
            f"{swap_analysis.get('used_mb', 0):.0f}/{swap_analysis.get('total_mb', 0):.0f} MB)"
        )

    # Sustained compressor RAM occupancy (0-2 points)
    compressor_pct = capacity_analysis.get("compressor_occupied_pct_of_ram", 0.0)
    if compressor_pct > 20:
        score += 2
        reasons.append(
            f"Compressor occupies {compressor_pct:.1f}% of physical RAM "
            f"({capacity_analysis.get('compressor_occupied_mb', 0):.0f} MB)"
        )
    elif compressor_pct > 10:
        score += 1
        reasons.append(
            f"Compressor occupancy elevated ({compressor_pct:.1f}% of RAM; "
            f"{capacity_analysis.get('compressor_occupied_mb', 0):.0f} MB)"
        )
    
    # Thrashing (0-3 points)
    thrash = reactivation_analysis.get('thrashing_count', 0)
    total = reactivation_analysis.get('total_intervals', 1)
    if thrash > 5:
        score += 3
        reasons.append(f"{thrash} thrashing episodes ({thrash/total*100:.0f}% of intervals)")
    elif thrash > 2:
        score += 2
        reasons.append(f"{thrash} thrashing episodes detected")
    elif thrash > 0:
        score += 1
        reasons.append(f"{thrash} thrashing episode(s) detected")
    
    # Free memory (0-3 points)
    avg_free = free_analysis.get('avg_mb', 1000)
    if avg_free < 100:
        score += 3
        reasons.append(f"Average free memory critically low ({avg_free:.0f} MB)")
    elif avg_free < 300:
        score += 2
        reasons.append(f"Average free memory low ({avg_free:.0f} MB)")
    elif avg_free < 500:
        score += 1
        reasons.append(f"Average free memory moderate ({avg_free:.0f} MB)")
    
    # Compression rate (0-2 points)
    avg_comp = compression_analysis.get('avg_compressions_per_interval', 0)
    if avg_comp > 100000:
        score += 2
        reasons.append(f"Very high compression rate ({avg_comp:.0f} pages/interval)")
    elif avg_comp > 20000:
        score += 1
        reasons.append(f"Elevated compression rate ({avg_comp:.0f} pages/interval)")
    
    score = min(score, 12)

    # Classification
    if score >= 9:
        level = "CRITICAL"
    elif score >= 6:
        level = "HIGH"
    elif score >= 3:
        level = "MODERATE"
    else:
        level = "LOW"
    
    return score, level, reasons


# ============================================================
# Report Generation
# ============================================================

def generate_report(
    mem_pressure,
    vm_stat_data,
    swap_info,
    processes,
    proc_summary,
    deltas,
    swap_analysis,
    compression_analysis,
    reactivation_analysis,
    free_analysis,
    phases,
    app_groups,
    top_movers,
    score,
    level,
    reasons,
    capacity_analysis,
    low_confidence,
    previous_comparison,
):
    """Generate markdown report."""
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total_ram_gb = mem_pressure.get('total_bytes', 0) / 1024**3 if mem_pressure.get('total_bytes') else 'Unknown'
    
    lines = []
    lines.append("# macOS Memory Pressure Report")
    lines.append(f"## Generated: {timestamp}")
    lines.append(
        f"## Physical RAM: {total_ram_gb:.0f} GB"
        if isinstance(total_ram_gb, float)
        else f"## Physical RAM: {total_ram_gb}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Verdict
    emoji = {"LOW": "🟢", "MODERATE": "🟡", "HIGH": "🔴", "CRITICAL": "🔴🔴"}
    if low_confidence:
        lines.append(
            f"## Verdict: ⚠️ LOW_CONFIDENCE {emoji.get(level, '')} {level} Pressure (Score: {score}/12)"
        )
    else:
        lines.append(f"## Verdict: {emoji.get(level, '')} {level} Pressure (Score: {score}/12)")
    lines.append("")
    lines.append("**Contributing factors:**")
    if low_confidence:
        lines.append(
            f"- Monitoring window is short ({len(deltas)} intervals; "
            f"recommended at least {MIN_CONFIDENT_INTERVALS})"
        )
    for r in reasons:
        lines.append(f"- {r}")
    if not reasons:
        lines.append("- No strong pressure indicators detected in this sample")
    lines.append("")
    
    # System Summary
    lines.append("---")
    lines.append("## System Summary")
    lines.append("")
    if mem_pressure:
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---|")
        if 'free_percentage' in mem_pressure:
            lines.append(f"| System-wide free % | {mem_pressure['free_percentage']}% |")
        lines.append(f"| Cumulative swapouts | {mem_pressure.get('swapouts', 'N/A'):,} pages |")
        lines.append(f"| Cumulative swapins | {mem_pressure.get('swapins', 'N/A'):,} pages |")
        lines.append(f"| Cumulative reactivations | {vm_stat_data.get('reactivated', 0):,} pages |")
        lines.append(f"| Cumulative compressions | {vm_stat_data.get('compressions', 0):,} |")
        lines.append(f"| Cumulative decompressions | {vm_stat_data.get('decompressions', 0):,} |")
    if capacity_analysis:
        lines.append(
            f"| Compressor RAM occupancy | {capacity_analysis.get('compressor_occupied_mb', 0):,.0f} MB "
            f"({capacity_analysis.get('compressor_occupied_pct_of_ram', 0):.1f}% of RAM) |"
        )
    if swap_info:
        lines.append(f"| Swap total | {swap_info.get('total_mb', 0):,.0f} MB |")
        lines.append(f"| Swap used | {swap_info.get('used_mb', 0):,.0f} MB ({swap_analysis.get('used_pct', 0):.1f}%) |")
    if proc_summary:
        lines.append(f"| Processes | {proc_summary.get('process_count', 'N/A')} |")
        lines.append(f"| Threads | {proc_summary.get('thread_count', 'N/A')} |")
        if 'load_avg' in proc_summary:
            la = proc_summary['load_avg']
            lines.append(f"| Load average | {la[0]:.2f}, {la[1]:.2f}, {la[2]:.2f} |")
    lines.append("")
    
    # Swap Analysis
    if swap_analysis and swap_analysis.get('total_intervals', 0) > 0:
        lines.append("---")
        lines.append("## Swap Activity")
        lines.append("")
        lines.append(
            f"During the {swap_analysis['total_intervals'] * DELTA_INTERVAL_SECONDS}s monitoring window:"
        )
        lines.append(f"- **Swapouts:** {swap_analysis.get('delta_total_swapouts', 0):,} pages ({pages_to_mb(swap_analysis.get('delta_total_swapouts', 0)):.1f} MB) in {swap_analysis.get('intervals_with_swapouts', 0)}/{swap_analysis['total_intervals']} intervals")
        lines.append(f"- **Swapins:** {swap_analysis.get('delta_total_swapins', 0):,} pages ({pages_to_mb(swap_analysis.get('delta_total_swapins', 0)):.1f} MB) in {swap_analysis.get('intervals_with_swapins', 0)}/{swap_analysis['total_intervals']} intervals")
        lines.append(
            f"- **Max swapout burst:** {swap_analysis.get('max_swapout_pages', 0):,} pages "
            f"({pages_to_mb(swap_analysis.get('max_swapout_pages', 0)):.1f} MB in {DELTA_INTERVAL_SECONDS}s)"
        )
        lines.append("")
    
    # Compression Analysis
    if compression_analysis:
        lines.append("---")
        lines.append("## Compression Activity")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Total compressed | {pages_to_gb(compression_analysis.get('total_compressions', 0)):.2f} GB |")
        lines.append(f"| Total decompressed | {pages_to_gb(compression_analysis.get('total_decompressions', 0)):.2f} GB |")
        lines.append(
            f"| Avg compression/{DELTA_INTERVAL_SECONDS}s | "
            f"{pages_to_mb(compression_analysis.get('avg_compressions_per_interval', 0)):.1f} MB |"
        )
        lines.append(
            f"| Peak compression/{DELTA_INTERVAL_SECONDS}s | "
            f"{pages_to_mb(compression_analysis.get('max_compressions', 0)):.1f} MB |"
        )
        lines.append(f"| Heavy compression intervals | {compression_analysis.get('heavy_compression_intervals', 0)}/{compression_analysis.get('total_intervals', 0)} |")
        cr_min, cr_max = compression_analysis.get('compressor_mb_range', (0, 0))
        cd_min, cd_max = compression_analysis.get('compressed_mb_range', (0, 0))
        lines.append(f"| Compressor RAM usage | {cr_min:.0f} - {cr_max:.0f} MB |")
        lines.append(f"| Data held compressed | {cd_min:.0f} - {cd_max:.0f} MB |")
        if compression_analysis.get('avg_compression_ratio', 0) > 0:
            lines.append(f"| Avg compression ratio | {compression_analysis['avg_compression_ratio']:.2f}:1 |")
        lines.append("")
    
    # Thrashing Analysis
    if reactivation_analysis:
        lines.append("---")
        lines.append("## Thrashing Analysis")
        lines.append("")
        lines.append(f"- **Total reactivations:** {reactivation_analysis.get('total_reactivations', 0):,} pages ({pages_to_gb(reactivation_analysis.get('total_reactivations', 0)):.2f} GB)")
        lines.append(
            f"- **Max in single {DELTA_INTERVAL_SECONDS}s:** "
            f"{reactivation_analysis.get('max_reactivations', 0):,} pages "
            f"({pages_to_mb(reactivation_analysis.get('max_reactivations', 0)):.1f} MB)"
        )
        lines.append(f"- **Heavy reactivation intervals:** {reactivation_analysis.get('heavy_intervals', 0)}/{reactivation_analysis.get('total_intervals', 0)}")
        lines.append(f"- **Thrashing episodes:** {reactivation_analysis.get('thrashing_count', 0)}/{reactivation_analysis.get('total_intervals', 0)} ({reactivation_analysis.get('thrashing_count', 0)/max(reactivation_analysis.get('total_intervals', 1), 1)*100:.1f}%)")
        lines.append("")
        
        episodes = reactivation_analysis.get('thrashing_episodes', [])
        if episodes:
            lines.append("| Time | Reactivations | Compressions | Decompressions | Swapouts |")
            lines.append("|---|---|---|---|---|")
            for ep in episodes:
                lines.append(f"| t={ep['time_s']}s | {ep['reactivations']:,} | {ep['compressions']:,} | {ep['decompressions']:,} | {ep['swapouts']:,} |")
            lines.append("")
    
    # Free Memory
    if free_analysis:
        lines.append("---")
        lines.append("## Free Memory")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---|")
        lines.append(f"| Minimum | {free_analysis.get('min_mb', 0):.0f} MB |")
        lines.append(f"| Maximum | {free_analysis.get('max_mb', 0):.0f} MB |")
        lines.append(f"| Average | {free_analysis.get('avg_mb', 0):.0f} MB |")
        lines.append(f"| Median | {free_analysis.get('median_mb', 0):.0f} MB |")
        lines.append(f"| Below 100 MB | {free_analysis.get('below_100mb', 0)}/{free_analysis.get('total_intervals', 0)} intervals ({free_analysis.get('below_100mb', 0)/max(free_analysis.get('total_intervals', 1), 1)*100:.0f}%) |")
        lines.append(f"| Below 500 MB | {free_analysis.get('below_500mb', 0)}/{free_analysis.get('total_intervals', 0)} intervals ({free_analysis.get('below_500mb', 0)/max(free_analysis.get('total_intervals', 1), 1)*100:.0f}%) |")
        lines.append("")
    
    # Phase Analysis
    if phases:
        lines.append("---")
        lines.append("## Phase Analysis (1-minute windows)")
        lines.append("")
        lines.append("| Time | Phase | Avg Free | Reactivations | Compressions | Swapouts |")
        lines.append("|---|---|---|---|---|---|")
        phase_emoji = {"CALM": "🟢", "ELEVATED": "🟡", "STORM": "🔴"}
        for p in phases:
            lines.append(f"| {p['start_s']}-{p['end_s']}s | {phase_emoji.get(p['phase'], '')} {p['phase']} | {p['avg_free_mb']:.0f} MB | {p['reactivations']:,} | {p['compressions']:,} | {p['swapouts']:,} |")
        
        calm_count = sum(1 for p in phases if p['phase'] == 'CALM')
        lines.append("")
        lines.append(f"**{calm_count}/{len(phases)} windows were calm ({calm_count/len(phases)*100:.0f}%)**")
        lines.append("")
    
    # Process Analysis
    if app_groups:
        lines.append("---")
        lines.append("## Application Memory Usage")
        lines.append("")
        lines.append("| Application | Resident | Compressed | Total Demand | Processes |")
        lines.append("|---|---|---|---|---|")
        
        sorted_apps = sorted(app_groups.items(), key=lambda x: x[1]['mem_mb'] + x[1]['cmprs_mb'], reverse=True)
        total_mem = 0
        total_cmprs = 0
        electron_total = 0
        electron_apps = ['Google Chrome', 'Cursor IDE', 'VS Code', 'Slack', 'Obsidian', 'Claude (desktop/code)', 'Arc Browser', 'Brave Browser', 'Discord']
        lsp_apps = ['rust-analyzer', 'gopls (Go LSP)', 'TypeScript LSP', 'SourceKit LSP', 'clangd (C++ LSP)', 'Python LSP']
        
        for app, data in sorted_apps:
            demand = data['mem_mb'] + data['cmprs_mb']
            total_mem += data['mem_mb']
            total_cmprs += data['cmprs_mb']
            if app in electron_apps:
                electron_total += demand
            lines.append(f"| **{app}** | {data['mem_mb']:,.0f} MB | {data['cmprs_mb']:,.0f} MB | {demand:,.0f} MB | {data['processes']} |")
        
        lines.append(f"| **TOTAL** | **{total_mem:,.0f} MB** | **{total_cmprs:,.0f} MB** | **{total_mem + total_cmprs:,.0f} MB** | |")
        lines.append("")
        
        if electron_total > 0:
            lines.append(f"**Electron/Chromium apps total: {electron_total:,.0f} MB ({electron_total/(total_mem+total_cmprs)*100:.0f}% of top processes)**")
            lines.append("")
        
        # LSP totals
        lsp_total = sum(app_groups.get(a, {}).get('mem_mb', 0) + app_groups.get(a, {}).get('cmprs_mb', 0) for a in lsp_apps if a in app_groups)
        if lsp_total > 0:
            lines.append(f"**Language server total: {lsp_total:,.0f} MB**")
            lines.append("")

    # Process Movers
    if top_movers:
        lines.append("---")
        lines.append("## Top Movers (Start → End)")
        lines.append("")
        lines.append("| Application | Start Demand | End Demand | Delta | Proc Count |")
        lines.append("|---|---|---|---|---|")
        for mover in top_movers:
            delta_mb = mover["delta_mb"]
            delta_sign = "+" if delta_mb >= 0 else ""
            lines.append(
                f"| **{mover['app']}** | {mover['start_mb']:,.0f} MB | {mover['end_mb']:,.0f} MB | "
                f"{delta_sign}{delta_mb:,.0f} MB | {mover['start_processes']} → {mover['end_processes']} |"
            )
        lines.append("")

    # Previous run comparison
    if previous_comparison:
        lines.append("---")
        lines.append("## Previous Run Comparison")
        lines.append("")
        if previous_comparison.get("previous_timestamp"):
            lines.append(f"Compared against run at `{previous_comparison['previous_timestamp']}`.")
            lines.append("")
        lines.append("| Metric | Previous | Current | Delta |")
        lines.append("|---|---|---|---|")
        for metric_name, unit in (
            ("score", ""),
            ("swap_used_mb", " MB"),
            ("swap_used_pct", "%"),
            ("avg_free_mb", " MB"),
            ("thrashing_count", ""),
            ("intervals", ""),
        ):
            previous_value = previous_comparison.get(f"previous_{metric_name}")
            current_value = previous_comparison.get(f"current_{metric_name}")
            delta_value = previous_comparison.get(f"delta_{metric_name}")

            def fmt(value, suffix: str) -> str:
                if value is None:
                    return "N/A"
                if isinstance(value, (int, float)):
                    if suffix == "%":
                        return f"{value:.1f}{suffix}"
                    if suffix == " MB":
                        return f"{value:,.0f}{suffix}"
                    return f"{value:,.0f}"
                return str(value)

            if isinstance(delta_value, (int, float)):
                delta_text = (
                    f"{'+' if delta_value >= 0 else ''}{delta_value:,.1f}{unit}"
                    if unit == "%"
                    else f"{'+' if delta_value >= 0 else ''}{delta_value:,.0f}{unit}"
                )
            else:
                delta_text = "N/A"

            lines.append(
                f"| {metric_name} | {fmt(previous_value, unit)} | {fmt(current_value, unit)} | {delta_text} |"
            )
        lines.append("")
    
    # Recommendations
    lines.append("---")
    lines.append("## Recommendations")
    lines.append("")
    
    if level in ("HIGH", "CRITICAL"):
        lines.append("### Immediate Actions")
        lines.append("")
        
        # Find biggest consumers
        if app_groups:
            sorted_apps = sorted(app_groups.items(), key=lambda x: x[1]['mem_mb'] + x[1]['cmprs_mb'], reverse=True)
            for app, data in sorted_apps[:5]:
                demand = data['mem_mb'] + data['cmprs_mb']
                if demand > 1000:
                    lines.append(f"- **{app}**: {demand:,.0f} MB — consider closing or reducing usage")
        
        # Check for duplicate IDEs
        ide_apps = [a for a in app_groups if a in ('Cursor IDE', 'VS Code', 'Xcode')]
        if len(ide_apps) > 1:
            lines.append(f"- **Duplicate IDEs detected ({', '.join(ide_apps)})**: Consolidate to one IDE to save significant memory")
        
        lines.append("")
    
    if level in ("MODERATE", "HIGH", "CRITICAL"):
        lines.append("### General Recommendations")
        lines.append("")
        lines.append("- Close unused browser tabs (each tab is a separate process)")
        lines.append("- Replace Electron apps with native alternatives where possible (e.g., Safari instead of Chrome, Zed instead of VS Code)")
        lines.append("- Kill idle VMs/containers (check Apple Virtualization, Docker, OrbStack)")
        lines.append("- Restart long-running Electron apps periodically (they leak memory)")
        lines.append("- Configure language server memory limits (gopls, rust-analyzer)")
        lines.append("")
    
    if level == "LOW" and not low_confidence:
        lines.append("Your system is healthy. No immediate action needed.")
        lines.append("")
    elif level == "LOW" and low_confidence:
        lines.append("This run is low confidence due to short monitoring duration.")
        lines.append("Collect at least ~1 minute of deltas before concluding the system is healthy.")
        lines.append("")
    
    # Estimated true demand
    if vm_stat_data.get('stored_in_compressor') and vm_stat_data.get('occupied_by_compressor'):
        stored = pages_to_mb(vm_stat_data['stored_in_compressor'])
        occupied = pages_to_mb(vm_stat_data['occupied_by_compressor'])
        active = pages_to_mb(vm_stat_data.get('pages_active', 0))
        wired = pages_to_mb(vm_stat_data.get('pages_wired', 0))
        swap_used = swap_info.get('used_mb', 0) if swap_info else 0
        est_demand = active + wired + stored + swap_used
        
        lines.append("---")
        lines.append("## Estimated True Memory Demand")
        lines.append("")
        lines.append(f"| Component | Size |")
        lines.append(f"|---|---|")
        lines.append(f"| Active + Speculative | {active + pages_to_mb(vm_stat_data.get('pages_speculative', 0)):,.0f} MB |")
        lines.append(f"| Wired | {wired:,.0f} MB |")
        lines.append(f"| Compressed (uncompressed) | {stored:,.0f} MB |")
        lines.append(f"| Swap used | {swap_used:,.0f} MB |")
        lines.append(f"| **Estimated total** | **{est_demand:,.0f} MB ({est_demand/1024:.1f} GB)** |")
        lines.append("")
        
        if isinstance(total_ram_gb, float) and total_ram_gb > 0:
            ratio = est_demand / 1024 / total_ram_gb
            lines.append(f"You're running at approximately **{ratio:.1f}x your physical RAM capacity**.")
            if ratio > 1.5:
                lines.append(f"Next machine recommendation: **{int(est_demand / 1024 / 8 + 1) * 8} GB RAM** minimum.")
            lines.append("")
    
    return '\n'.join(lines)


# ============================================================
# Main
# ============================================================

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Analyze collected macOS memory metrics and generate a report."
    )
    parser.add_argument(
        "data_dir",
        type=Path,
        help=(
            "Directory containing memory_pressure.txt, vm_stat.txt, "
            "top_output.txt (or top_output_start.txt), optional top_output_end.txt, "
            "swap.txt, vm_stat_deltas.txt, and optional analysis_previous.json"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run analysis and write markdown/json outputs."""
    args = parse_args(argv)
    data_dir: Path = args.data_dir

    if not data_dir.exists():
        print(f"Error: Directory {data_dir} does not exist")
        return 1
    if not data_dir.is_dir():
        print(f"Error: {data_dir} is not a directory")
        return 1

    global PAGE_SIZE
    PAGE_SIZE = detect_page_size(data_dir)

    print(f"Reading data from {data_dir}...")
    print(f"Detected page size: {PAGE_SIZE} bytes")
    print("")

    # Parse all data sources
    mem_pressure = parse_memory_pressure(data_dir / "memory_pressure.txt")
    vm_stat_data = parse_vm_stat(data_dir / "vm_stat.txt")
    swap_info = parse_swap(data_dir / "swap.txt")
    top_start_path = data_dir / "top_output.txt"
    if not top_start_path.exists():
        top_start_path = data_dir / "top_output_start.txt"
    processes_start, proc_summary = parse_top_output(top_start_path)
    processes_end, _ = parse_top_output(data_dir / "top_output_end.txt")
    deltas = parse_vm_stat_deltas(data_dir / "vm_stat_deltas.txt")

    print(
        f"Parsed: memory_pressure={'OK' if mem_pressure else 'MISSING'}, "
        f"vm_stat={'OK' if vm_stat_data else 'MISSING'}, "
        f"swap={'OK' if swap_info else 'MISSING'}, "
        f"processes_start={len(processes_start)}, "
        f"processes_end={len(processes_end)}, "
        f"vm_stat_deltas={len(deltas)} intervals"
    )
    print("")

    if not deltas:
        print("Warning: No valid vm_stat delta rows found in vm_stat_deltas.txt.")
        print(
            "Hint: On current macOS, collect with `vm_stat -c 24 5` "
            "(or `vm_stat -c 4 1` for a quick test)."
        )
        print("")
    low_confidence = len(deltas) < MIN_CONFIDENT_INTERVALS
    if low_confidence:
        observed = len(deltas) * DELTA_INTERVAL_SECONDS
        expected = MIN_CONFIDENT_INTERVALS * DELTA_INTERVAL_SECONDS
        print(
            f"Warning: Low-confidence sample window ({observed}s observed; "
            f"recommend at least {expected}s)."
        )
        print("")

    # Run analyses
    swap_analysis = analyze_swap(mem_pressure, vm_stat_data, swap_info, deltas)
    capacity_analysis = analyze_capacity(mem_pressure, vm_stat_data)
    compression_analysis = analyze_compression(deltas)
    reactivation_analysis = analyze_reactivations(deltas)
    free_analysis = analyze_free_memory(deltas)
    phases = analyze_phases(deltas)
    app_groups = group_processes(processes_start)
    app_groups_end = group_processes(processes_end)
    top_movers = compute_top_movers(app_groups, app_groups_end)

    # Calculate score
    score, level, reasons = calculate_pressure_score(
        swap_analysis,
        reactivation_analysis,
        free_analysis,
        compression_analysis,
        capacity_analysis,
    )

    # Print summary to stdout
    print("=" * 60)
    confidence_suffix = " [LOW_CONFIDENCE]" if low_confidence else ""
    print(f"PRESSURE: {level}{confidence_suffix} (Score: {score}/12)")
    print("=" * 60)
    for reason in reasons:
        print(f"  • {reason}")
    if not reasons:
        print("  • No significant pressure indicators found in parsed input.")
    print("")

    if deltas:
        print(
            f"Monitoring window: {len(deltas)} intervals × {DELTA_INTERVAL_SECONDS}s "
            f"= {len(deltas) * DELTA_INTERVAL_SECONDS}s"
        )
        print(
            f"Thrashing episodes: {reactivation_analysis.get('thrashing_count', 0)}/{len(deltas)}"
        )
        print(
            f"Free memory: avg={free_analysis.get('avg_mb', 0):.0f} MB, "
            f"min={free_analysis.get('min_mb', 0):.0f} MB"
        )
        print("")

    if swap_info:
        print(
            f"Swap: {swap_info.get('used_mb', 0):,.0f} / {swap_info.get('total_mb', 0):,.0f} MB "
            f"({swap_analysis.get('used_pct', 0):.1f}%)"
        )
        print("")

    if app_groups:
        print("Top memory consumers:")
        sorted_apps = sorted(
            app_groups.items(),
            key=lambda item: item[1]["mem_mb"] + item[1]["cmprs_mb"],
            reverse=True,
        )
        for app, data in sorted_apps[:7]:
            demand = data["mem_mb"] + data["cmprs_mb"]
            print(f"  {app:<30s} {demand:>8,.0f} MB ({data['processes']} proc)")
        print("")

    if top_movers:
        print("Top movers (start -> end):")
        for mover in top_movers[:5]:
            delta_sign = "+" if mover["delta_mb"] >= 0 else ""
            print(
                f"  {mover['app']:<30s} {mover['start_mb']:>7,.0f} -> {mover['end_mb']:>7,.0f} MB "
                f"({delta_sign}{mover['delta_mb']:,.0f} MB)"
            )
        print("")

    run_summary = {
        "timestamp": datetime.now().isoformat(),
        "score": score,
        "level": level,
        "swap_used_mb": swap_analysis.get("used_mb", 0),
        "swap_used_pct": swap_analysis.get("used_pct", 0),
        "avg_free_mb": free_analysis.get("avg_mb", 0),
        "thrashing_count": reactivation_analysis.get("thrashing_count", 0),
        "intervals": len(deltas),
        "low_confidence": low_confidence,
    }

    previous_analysis = load_json_file(data_dir / "analysis_previous.json")
    previous_comparison = compare_with_previous_run(run_summary, previous_analysis)
    if previous_comparison:
        delta_score = previous_comparison.get("delta_score")
        delta_swap_pct = previous_comparison.get("delta_swap_used_pct")
        score_text = f"{delta_score:+.0f}" if isinstance(delta_score, (int, float)) else "N/A"
        swap_text = (
            f"{delta_swap_pct:+.1f}%"
            if isinstance(delta_swap_pct, (int, float))
            else "N/A"
        )
        print(
            "Compared with analysis_previous.json: "
            f"score {score_text}, swap usage {swap_text}."
        )
        print("")

    # Generate and save report
    report = generate_report(
        mem_pressure,
        vm_stat_data,
        swap_info,
        processes_start,
        proc_summary,
        deltas,
        swap_analysis,
        compression_analysis,
        reactivation_analysis,
        free_analysis,
        phases,
        app_groups,
        top_movers,
        score,
        level,
        reasons,
        capacity_analysis,
        low_confidence,
        previous_comparison,
    )

    report_path = data_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Full report saved to: {report_path}")

    # Also save raw analysis as JSON for programmatic use
    analysis_json = {
        "timestamp": run_summary["timestamp"],
        "score": score,
        "level": level,
        "low_confidence": low_confidence,
        "reasons": reasons,
        "run_summary": run_summary,
        "swap": swap_analysis,
        "capacity": capacity_analysis,
        "compression": {k: v for k, v in compression_analysis.items() if k != "compression_ratios"},
        "reactivation": {k: v for k, v in reactivation_analysis.items() if k != "thrashing_episodes"},
        "free_memory": free_analysis,
        "top_movers": top_movers,
        "comparison_to_previous": previous_comparison,
        "phase_summary": {
            "calm": sum(1 for phase in phases if phase["phase"] == "CALM"),
            "elevated": sum(1 for phase in phases if phase["phase"] == "ELEVATED"),
            "storm": sum(1 for phase in phases if phase["phase"] == "STORM"),
        },
    }

    json_path = data_dir / "analysis.json"
    json_path.write_text(json.dumps(analysis_json, indent=2, default=str), encoding="utf-8")
    print(f"JSON analysis saved to: {json_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
