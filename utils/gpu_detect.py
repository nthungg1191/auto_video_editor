"""Utility: detect NVIDIA GPU, NVENC support, and system resources via FFmpeg / nvidia-smi."""

import subprocess
import re
from pathlib import Path

# Local bin path detection
LOCAL_BIN_DIR = Path(__file__).parent.parent / "bin"
FFMPEG_PATH = str(LOCAL_BIN_DIR / "ffmpeg.exe") if (LOCAL_BIN_DIR / "ffmpeg.exe").exists() else "ffmpeg"
FFPROBE_PATH = str(LOCAL_BIN_DIR / "ffprobe.exe") if (LOCAL_BIN_DIR / "ffprobe.exe").exists() else "ffprobe"


def detect_gpu() -> dict:
    """
    Returns dict with keys:
      - available (bool)
      - name (str)
      - nvenc_h264 (bool)
      - nvenc_hevc (bool)
    """
    info = {"available": False, "name": "Không tìm thấy GPU", "nvenc_h264": False, "nvenc_hevc": False}

    # Check nvidia-smi
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, encoding="utf-8", errors="replace", timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            info["available"] = True
            info["name"] = r.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass

    # Check FFmpeg NVENC encoders
    try:
        r = subprocess.run([FFMPEG_PATH, "-encoders"], capture_output=True, encoding="utf-8", errors="replace", timeout=10)
        out = r.stdout + r.stderr
        if "h264_nvenc" in out:
            info["nvenc_h264"] = True
        if "hevc_nvenc" in out:
            info["nvenc_hevc"] = True
    except Exception:
        pass

    return info


def check_ffmpeg() -> bool:
    try:
        subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def check_ffprobe() -> bool:
    try:
        subprocess.run([FFPROBE_PATH, "-version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def detect_system_info() -> dict:
    """
    Returns dict with keys:
      - cpu_name       (str)
      - cpu_load_pct   (int)   -- live system-wide CPU usage 0-100
      - ram_total_gb   (float)
      - ram_free_gb    (float)
      - ram_used_pct   (int)   -- live RAM usage 0-100
      - gpu_name       (str)
      - gpu_available  (bool)
      - vram_total_mb  (int)
      - vram_free_mb   (int)
      - gpu_power_w    (str)
    """
    info = {
        "cpu_name": "—",
        "cpu_load_pct": 0,
        "ram_total_gb": 0,
        "ram_free_gb": 0,
        "ram_used_pct": 0,
        "gpu_name": "Khong co GPU",
        "gpu_available": False,
        "vram_total_mb": 0,
        "vram_free_mb": 0,
        "gpu_power_w": "—",
    }

    # CPU name via wmic
    try:
        r = subprocess.run(
            ["wmic", "cpu", "get", "Name"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=5
        )
        if r.returncode == 0:
            lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
            if len(lines) > 1:
                info["cpu_name"] = lines[1]
    except Exception:
        pass

    # CPU load % via wmic
    try:
        r = subprocess.run(
            ["wmic", "cpu", "get", "loadpercentage"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=5
        )
        if r.returncode == 0:
            lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip() and l.strip().isdigit()]
            if lines:
                info["cpu_load_pct"] = int(lines[-1])
    except Exception:
        pass

    # RAM via wmic OS
    try:
        r = subprocess.run(
            ["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory", "/format:list"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=5
        )
        if r.returncode == 0:
            total_kb = 0
            free_kb = 0
            for line in r.stdout.splitlines():
                if "TotalVisibleMemorySize" in line:
                    val = line.split("=")[-1].strip()
                    total_kb = int(val)
                    info["ram_total_gb"] = round(total_kb / (1024 ** 2), 1)
                elif "FreePhysicalMemory" in line:
                    val = line.split("=")[-1].strip()
                    free_kb = int(val)
                    info["ram_free_gb"] = round(free_kb / (1024 ** 2), 1)
            if total_kb > 0:
                info["ram_used_pct"] = int(round((1 - free_kb / total_kb) * 100))
    except Exception:
        pass

    # GPU via nvidia-smi (CSV: name, vram_total_MB, vram_free_MB, power_W)
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.free,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            info["gpu_available"] = True
            info["gpu_name"] = parts[0]
            if len(parts) >= 4:
                info["vram_total_mb"] = int(parts[1])
                info["vram_free_mb"] = int(parts[2])
                info["gpu_power_w"] = parts[3] + " W"
            elif len(parts) >= 2:
                info["vram_total_mb"] = int(parts[1])
    except Exception:
        pass

    return info
