"""Hardware/system information utilities for Nox."""

from __future__ import annotations

import os
import platform
from typing import Optional

__all__ = ["hardware_summary"]


def hardware_summary() -> str:
    """Return a concise description of the current host hardware."""

    uname = platform.uname()
    parts: list[str] = []
    os_part = f"OS: {uname.system} {uname.release}".strip()
    if uname.version:
        os_part += f" ({uname.version})"
    parts.append(os_part)

    machine = uname.machine or platform.processor() or "unknown"
    parts.append(f"Machine: {machine}")

    processor = uname.processor or platform.processor() or "unknown"
    parts.append(f"Processor: {processor}")

    cpu_count = os.cpu_count()
    if cpu_count:
        parts.append(f"CPUs: {cpu_count}")

    memory_gb = _total_memory_gb()
    if memory_gb is not None:
        parts.append(f"Memory: {memory_gb:.1f} GB")

    return "; ".join(parts)


def _total_memory_gb() -> Optional[float]:
    """Best-effort physical memory size in gigabytes."""

    # Linux: read /proc/meminfo
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    tokens = line.split()
                    if len(tokens) >= 2:
                        # Value is in kB
                        kb = float(tokens[1])
                        return kb / (1024 * 1024)
    except FileNotFoundError:
        pass
    except Exception:
        return None

    # macOS: try sysctl
    try:
        import subprocess

        output = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
        bytes_val = float(output.strip())
        return bytes_val / (1024 ** 3)
    except Exception:
        pass

    # Fallback using sysconf (Unix)
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        if page_size > 0 and phys_pages > 0:
            return (page_size * phys_pages) / (1024 ** 3)
    except (ValueError, OSError, AttributeError):
        pass

    return None
