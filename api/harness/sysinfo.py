from __future__ import annotations

import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any

_HOST_HINTS = (
    "内存",
    "运存",
    "处理器",
    "磁盘",
    "硬盘",
    "运行时间",
    "开机多久",
    "操作系统",
    "系统版本",
    "主机信息",
    "机器配置",
    "电脑配置",
)
_HOST_RE = re.compile(
    r"\b(ram|memory|cpu|disk|storage|uptime|os version|free -h|df -h|lscpu|top)\b",
    re.I,
)


def wants_host_info(text: str) -> bool:
    value = (text or "").strip()
    if not value or len(value) > 200:
        return False
    if any(hint in value for hint in _HOST_HINTS):
        return True
    return bool(_HOST_RE.search(value))


def human_bytes(value: int | float | None) -> str:
    if value is None:
        return ""
    size = float(value)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    if index == 0:
        return f"{int(size)} {units[index]}"
    return f"{size:.1f} {units[index]}"


def _memory() -> dict[str, Any] | None:
    proc = Path("/proc/meminfo")
    try:
        if proc.is_file():
            values: dict[str, int] = {}
            for line in proc.read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, rest = line.partition(":")
                if not rest:
                    continue
                try:
                    values[key.strip()] = int(rest.strip().split()[0]) * 1024
                except (ValueError, IndexError):
                    continue
            total = values.get("MemTotal")
            available = values.get("MemAvailable", values.get("MemFree"))
            if total and available is not None:
                return _memory_payload(total, available, "procfs")
    except OSError:
        pass

    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return _memory_payload(int(status.ullTotalPhys), int(status.ullAvailPhys), "win32")
        except Exception:
            pass

    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            available = None
            if "SC_AVPHYS_PAGES" in os.sysconf_names:
                available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            if total:
                return _memory_payload(int(total), int(available) if available else None, "sysconf")
    except (ValueError, OSError):
        pass
    return None


def _memory_payload(total: int, available: int | None, source: str) -> dict[str, Any]:
    used = max(0, total - available) if available is not None else None
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "total_human": human_bytes(total),
        "available_human": human_bytes(available),
        "used_human": human_bytes(used),
        "source": source,
    }


def _cpu_model() -> str:
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _uptime_seconds() -> float | None:
    try:
        proc = Path("/proc/uptime")
        if proc.is_file():
            return float(proc.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        pass
    if os.name == "nt":
        try:
            import ctypes

            return float(ctypes.windll.kernel32.GetTickCount64()) / 1000.0
        except Exception:
            pass
    return None


def _disk(base: Path) -> dict[str, Any] | None:
    try:
        usage = shutil.disk_usage(str(base))
    except OSError:
        return None
    return {
        "path": str(base),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "total_human": human_bytes(usage.total),
        "used_human": human_bytes(usage.used),
        "free_human": human_bytes(usage.free),
    }


def collect(base_path: str = "") -> dict[str, Any]:
    base = Path(base_path) if base_path else Path.home()
    try:
        base = base.expanduser()
    except (OSError, RuntimeError):
        base = Path.home()
    return {
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "cpu_model": _cpu_model(),
        "memory": _memory(),
        "disk": _disk(base),
        "uptime_seconds": _uptime_seconds(),
        "base_path": str(base),
    }


def summary(data: dict[str, Any]) -> str:
    lines = [
        f"OS: {data.get('os') or 'unknown'}",
        f"CPU: {data.get('cpu_count') or '?'} core(s) · {data.get('cpu_model') or 'unknown'}",
    ]
    memory = data.get("memory") or {}
    if memory:
        lines.append(
            "Memory: "
            f"{memory.get('total_human')} total · "
            f"{memory.get('available_human')} available · "
            f"{memory.get('used_human')} used"
        )
    else:
        lines.append("Memory: unavailable")
    disk = data.get("disk") or {}
    if disk:
        lines.append(
            "Disk: "
            f"{disk.get('total_human')} total · "
            f"{disk.get('free_human')} free · "
            f"{disk.get('used_human')} used ({disk.get('path')})"
        )
    uptime = data.get("uptime_seconds")
    if uptime is not None:
        total = int(uptime)
        days, rest = divmod(total, 86400)
        hours, rest = divmod(rest, 3600)
        minutes = rest // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        lines.append("Uptime: " + " ".join(parts))
    return "\n".join(lines)
