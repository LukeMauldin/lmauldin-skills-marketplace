---
name: macos-memory-pressure
description: Analyze macOS memory pressure by collecting system metrics and generating a comprehensive report. Run this skill when asked to check memory pressure, diagnose memory issues, or analyze RAM usage on macOS.
---

# macOS Memory Pressure Analysis

This skill collects memory statistics from macOS, analyzes them with Python, and produces a detailed pressure report with actionable recommendations.

## When to Use

- User asks to check memory pressure or RAM usage
- User says their Mac feels slow and suspects memory
- User wants to understand what's eating their RAM
- User asks to "run the memory analysis" or similar

## Prerequisites

- Must be running on macOS (Darwin)
- Python 3 must be available
- Some commands may require `sudo` for full swap details (the skill handles the case where sudo is unavailable)

## Workflow

### Step 1: Collect System Metrics

Run the following data collection commands and capture their output to files:

```bash
# Create working directory
mkdir -p /tmp/memory-analysis

# 1. Memory pressure summary
memory_pressure > /tmp/memory-analysis/memory_pressure.txt 2>&1

# 2. VM statistics snapshot
vm_stat > /tmp/memory-analysis/vm_stat.txt 2>&1

# 3. Top processes sorted by memory (top 25)
top -l 1 -o mem -n 25 > /tmp/memory-analysis/top_output.txt 2>&1

# 4. Swap usage (try with sudo, fall back to non-sudo)
sudo sysctl vm.swapusage 2>/dev/null > /tmp/memory-analysis/swap.txt || sysctl vm.swapusage > /tmp/memory-analysis/swap.txt 2>&1

# 5. Real-time vm_stat deltas (5-second intervals for ~2 minutes)
# This is the most important data source — it shows live pressure
# macOS-native form: count=24 samples at 5s each (~120s)
vm_stat -c 24 5 > /tmp/memory-analysis/vm_stat_deltas.txt 2>&1

# 6. End-of-window top snapshot (used to detect memory movers)
top -l 1 -o mem -n 25 > /tmp/memory-analysis/top_output_end.txt 2>&1
```

**Important:** The `vm_stat -c 24 5` command runs for about 2 minutes to capture meaningful data. Do NOT skip this step — the delta data is essential for distinguishing between steady-state pressure and bursty thrashing.

### Step 2: Run the Analysis Script

After collecting data, run the Python analysis script at `scripts/analyze.py`.

`<path-to-this-skill>` means the directory that contains this `SKILL.md` file:

```bash
python3 <path-to-this-skill>/scripts/analyze.py /tmp/memory-analysis
```

The script reads all collected files and outputs a structured analysis to stdout AND writes a markdown report to `/tmp/memory-analysis/report.md`.

Notes:
- If `top_output_end.txt` exists, the report includes a **Top Movers (Start → End)** section.
- If `analysis_previous.json` exists, the script includes a **Previous Run Comparison** section.
- If fewer than ~12 vm_stat delta intervals are present (about 60s), the verdict is marked **LOW_CONFIDENCE**.

### Step 3: Present Findings

After the script completes:

1. Read `/tmp/memory-analysis/report.md`
2. Present the key findings to the user conversationally, focusing on:
   - Overall pressure classification (LOW / MODERATE / HIGH / CRITICAL)
   - Confidence level (normal vs LOW_CONFIDENCE)
   - The top 3-5 memory consumers grouped by application
   - Top movers between start/end snapshots (if collected)
   - Whether thrashing episodes were detected
   - Swap status and trend
   - Comparison with prior run (if `analysis_previous.json` exists)
   - Specific, prioritized recommendations
3. Offer to re-run after the user makes changes to compare before/after

### Interpreting Results

**Pressure Score Guide:**
- 0-2: LOW — system is healthy, no action needed
- 3-5: MODERATE — some pressure, consider closing unused apps
- 6-8: HIGH — active pressure affecting performance, action recommended  
- 9-12: CRITICAL — severe thrashing, immediate action needed

**Key Metrics to Highlight:**
- **Thrashing episodes**: Intervals where reactivations > 50K AND compressions > 50K simultaneously. This is the clearest sign of real user-visible performance degradation.
- **Swap growth**: If swap used is growing between measurements, pressure is escalating.
- **Free memory < 100 MB**: System is running on fumes. The compressor and swap are doing all the work.
- **Compression ratio**: A ratio > 3:1 means the compressor is working hard. The higher the ratio, the more aggressive the compression.

**Common Culprits:**
- Electron apps (Chrome, VS Code, Cursor, Slack, Discord, Obsidian) each run a full Chromium instance
- Language servers (rust-analyzer, gopls, typescript-language-server) can quietly consume gigabytes
- Docker/OrbStack/Apple Virtualization holding memory for idle VMs
- Browser tabs — each is a separate process

### Re-running for Comparison

If the user made changes and wants to compare, archive the previous JSON first. The script automatically compares against `/tmp/memory-analysis/analysis_previous.json` when present.

```bash
# Archive previous run
cp /tmp/memory-analysis/report.md /tmp/memory-analysis/report_previous.md
cp /tmp/memory-analysis/analysis.json /tmp/memory-analysis/analysis_previous.json
rm /tmp/memory-analysis/memory_pressure.txt /tmp/memory-analysis/vm_stat.txt /tmp/memory-analysis/top_output.txt /tmp/memory-analysis/top_output_end.txt /tmp/memory-analysis/swap.txt /tmp/memory-analysis/vm_stat_deltas.txt
```

Then repeat Steps 1-3.
