# PubCast AI — doctor.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Doctor mode for PubCast.

Runs practical environment and filesystem checks so operators can verify a
machine before trying to go live. Designed to stay lightweight: optional
subsystems degrade to warnings instead of hard failures in minimal setups.

This version adds:
- launch gating (clear go / no-go decision)
- smarter port conflict reporting (attempt process discovery)
- per-check fix instructions
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class DoctorCheck:
    check_id: str
    name: str
    status: str  # pass | warn | fail
    required: bool
    message: str
    detail: Dict[str, Any]
    fix_instructions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PortProbeResult:
    port: int
    label: str
    listening: bool
    owner: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _current_profile() -> str:
    return (os.getenv("PUBCAST_PROFILE") or "minimal").strip().lower() or "minimal"


def _module_available(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _maybe_import_psutil() -> Any:
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:
        return None


def _run_command(args: List[str]) -> Optional[str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=1.5, check=False)
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return output.strip() or None
    except Exception:
        return None


def _normalize_owner(process_name: Optional[str], pid: Optional[int], command: Optional[str], source: str) -> Optional[Dict[str, Any]]:
    if not process_name and not pid and not command:
        return None
    return {
        "pid": pid,
        "name": process_name,
        "command": command,
        "source": source,
    }


def _find_port_owner(port: int) -> Optional[Dict[str, Any]]:
    psutil = _maybe_import_psutil()
    if psutil is not None:
        try:
            for conn in psutil.net_connections(kind="inet"):
                if not conn.laddr:
                    continue
                if getattr(conn.laddr, "port", None) != port:
                    continue
                if conn.status != psutil.CONN_LISTEN:
                    continue
                pid = conn.pid
                if pid:
                    try:
                        proc = psutil.Process(pid)
                        cmdline = " ".join(proc.cmdline()) if proc.cmdline() else None
                        return _normalize_owner(proc.name(), pid, cmdline, "psutil")
                    except Exception:
                        return _normalize_owner(None, pid, None, "psutil")
                return _normalize_owner(None, None, None, "psutil")
        except Exception:
            pass

    system = platform.system().lower()

    if system == "windows":
        netstat = _run_command(["netstat", "-ano"])
        if netstat:
            for line in netstat.splitlines():
                if f":{port}" not in line or "LISTENING" not in line.upper():
                    continue
                parts = line.split()
                pid = None
                try:
                    pid = int(parts[-1])
                except Exception:
                    pid = None
                tasklist = _run_command(["tasklist", "/FI", f"PID eq {pid}"]) if pid else None
                return _normalize_owner(tasklist.splitlines()[-1] if tasklist else None, pid, tasklist, "netstat")

    lsof = _run_command(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"])
    if lsof:
        lines = [line for line in lsof.splitlines() if line.strip()]
        if len(lines) >= 2:
            parts = lines[1].split()
            process_name = parts[0] if len(parts) > 0 else None
            pid = None
            try:
                pid = int(parts[1]) if len(parts) > 1 else None
            except Exception:
                pid = None
            return _normalize_owner(process_name, pid, lines[1], "lsof")

    ss = _run_command(["ss", "-ltnp"])
    if ss:
        for line in ss.splitlines():
            if f":{port} " not in line and not line.rstrip().endswith(f":{port}"):
                continue
            pid = None
            name = None
            command = line.strip()
            if 'pid=' in line:
                try:
                    pid = int(line.split('pid=')[1].split(',')[0])
                except Exception:
                    pid = None
            if 'users:(("' in line:
                try:
                    name = line.split('users:(("', 1)[1].split('"', 1)[0]
                except Exception:
                    name = None
            return _normalize_owner(name, pid, command, "ss")

    netstat = _run_command(["netstat", "-ltnp"])
    if netstat:
        for line in netstat.splitlines():
            if f":{port} " not in line and not line.rstrip().endswith(f":{port}"):
                continue
            return _normalize_owner(None, None, line.strip(), "netstat")

    return None


def _probe_port(label: str, port: int) -> PortProbeResult:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        listening = sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()
    owner = _find_port_owner(port) if listening else None
    return PortProbeResult(port=port, label=label, listening=listening, owner=owner)


def _status_message_for_port(probe: PortProbeResult, expected: bool = False) -> str:
    if not probe.listening:
        return f"Port {probe.port} is free"
    owner = probe.owner or {}
    owner_name = owner.get("name") or "unknown process"
    pid = owner.get("pid")
    pid_part = f" (pid {pid})" if pid else ""
    prefix = "Expected listener" if expected else "Port conflict"
    return f"{prefix} on {probe.port}: {owner_name}{pid_part}"


def _check_python() -> DoctorCheck:
    version = sys.version_info
    ok = (version.major, version.minor) >= (3, 10)
    fixes = []
    if not ok:
        fixes = [
            "Install Python 3.10 or newer.",
            "Recreate your virtual environment with the newer interpreter.",
        ]
    return DoctorCheck(
        check_id="python_version",
        name="Python version",
        status="pass" if ok else "fail",
        required=True,
        message=f"Python {version.major}.{version.minor}.{version.micro}",
        detail={"minimum": "3.10", "current": platform.python_version()},
        fix_instructions=fixes,
    )


def _check_core_imports() -> DoctorCheck:
    missing = [name for name in ("fastapi", "uvicorn") if not _module_available(name)]
    ok = not missing
    fixes = []
    if not ok:
        fixes = [
            "Install core server packages with: pip install -r requirements.txt",
            "If you are using minimal mode, verify requirements-minimal.txt still includes FastAPI and Uvicorn.",
        ]
    return DoctorCheck(
        check_id="core_imports",
        name="Core server dependencies",
        status="pass" if ok else "fail",
        required=True,
        message="Core imports available" if ok else f"Missing imports: {', '.join(missing)}",
        detail={"missing": missing},
        fix_instructions=fixes,
    )


def _check_data_dirs(base_dir: Path) -> DoctorCheck:
    # Resolve data_root regardless of whether the caller passed the project
    # root or DATA_DIR directly.
    # Sentinel: the project root always contains main.py and requirements.txt.
    # If those exist as siblings, base_dir is the project root → data is a child.
    # Otherwise base_dir IS the data directory.
    if (base_dir / "main.py").exists() or (base_dir / "requirements.txt").exists():
        data_root = base_dir / "data"
    else:
        data_root = base_dir

    required_dirs = [
        data_root,
        data_root / "recordings",
        data_root / "emergency_saves",
        data_root / "exports",
        data_root / "byok",
        data_root / "credentials",
    ]
    missing = [str(path.relative_to(data_root.parent)) for path in required_dirs if not path.exists()]
    ok = not missing
    fixes = []
    if not ok:
        fixes = [
            f"Create the missing folders under {data_root}.",
            "If your app usually bootstraps these folders, run that init step before going live.",
        ]
    return DoctorCheck(
        check_id="data_dirs",
        name="Required data directories",
        status="pass" if ok else "fail",
        required=True,
        message="All required data directories exist" if ok else f"Missing: {', '.join(missing)}",
        detail={"checked": [str(path.relative_to(data_root.parent)) for path in required_dirs], "missing": missing},
        fix_instructions=fixes,
    )


def _check_write_access(base_dir: Path) -> DoctorCheck:
    # Same sentinel as _check_data_dirs: detect project root vs DATA_DIR.
    if (base_dir / "main.py").exists() or (base_dir / "requirements.txt").exists():
        data_root = base_dir / "data"
    else:
        data_root = base_dir

    targets = [
        data_root / "recordings",
        data_root / "emergency_saves",
        data_root / "exports",
    ]
    failed: List[str] = []
    for target in targets:
        try:
            target.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="doctor_", suffix=".tmp", dir=target, delete=True) as tmp:
                tmp.write(b"ok")
                tmp.flush()
        except Exception:
            failed.append(str(target.relative_to(data_root.parent)))
    ok = not failed
    fixes = []
    if not ok:
        fixes = [
            "Fix folder permissions for data/recordings, data/emergency_saves, and data/exports.",
            "Run the app from a user account that can write to the project data directory.",
            "If this is a protected location, move the project somewhere user-writable and rerun Doctor.",
        ]
    return DoctorCheck(
        check_id="write_access",
        name="Writable recording paths",
        status="pass" if ok else "fail",
        required=True,
        message="Recording and emergency-save paths are writable" if ok else f"Not writable: {', '.join(failed)}",
        detail={"targets": [str(path.relative_to(data_root.parent)) for path in targets], "failed": failed},
        fix_instructions=fixes,
    )


def _check_disk_space(base_dir: Path) -> DoctorCheck:
    usage = shutil.disk_usage(base_dir)
    free_gb = usage.free / (1024 ** 3)
    ok = free_gb >= 1.0
    status = "pass" if ok else "warn"
    fixes = []
    if not ok:
        fixes = [
            "Free at least 1 GB of disk space before recording or exporting.",
            "Clear old recordings, exports, or temp files from the data directory.",
        ]
    return DoctorCheck(
        check_id="disk_space",
        name="Available disk space",
        status=status,
        required=False,
        message=f"{free_gb:.2f} GB free",
        detail={"free_bytes": usage.free, "threshold_gb": 1.0},
        fix_instructions=fixes,
    )


def _check_ffmpeg() -> DoctorCheck:
    path = shutil.which("ffmpeg")
    ok = path is not None
    fixes = []
    if not ok:
        fixes = [
            "Install FFmpeg if you need export/transcode features.",
            "Keep using minimal mode if live web control matters more than media export on this machine.",
        ]
    return DoctorCheck(
        check_id="ffmpeg",
        name="FFmpeg",
        status="pass" if ok else "warn",
        required=False,
        message="FFmpeg found" if ok else "FFmpeg not found — export/transcode features may be limited",
        detail={"path": path},
        fix_instructions=fixes,
    )


def _check_sounddevice() -> DoctorCheck:
    source = "modules.audio_devices"
    try:
        from modules import audio_devices

        available = bool(getattr(audio_devices, "_SD_AVAILABLE", False))
    except Exception:
        source = "sounddevice import"
        available = _module_available("sounddevice")

    fixes = []
    if not available:
        fixes = [
            "Ignore this on low-requirement browser-first setups.",
            "Install PortAudio and sounddevice only if you need server-side device enumeration.",
        ]

    return DoctorCheck(
        check_id="sounddevice",
        name="Server audio enumeration",
        status="pass" if available else "warn",
        required=False,
        message="sounddevice available" if available else "sounddevice unavailable — browser-side mic tests only",
        detail={"available": available, "source": source},
        fix_instructions=fixes,
    )


def _check_rust_bridge_binary(base_dir: Path, profile: str) -> DoctorCheck:
    binary = base_dir / "bin" / "ws_renderer"
    exists = binary.exists() and os.access(binary, os.X_OK)
    required = profile == "full"
    if exists:
        status = "pass"
        message = "Rust bridge binary is present"
        fixes: List[str] = []
    elif required:
        status = "fail"
        message = "Rust bridge binary missing for full profile"
        fixes = [
            "Build the Rust bridge: cd rust_crate && cargo build --release",
            "Copy the built binary into bin/ws_renderer and rerun Doctor.",
            "If this machine should stay lightweight, switch to PUBCAST_PROFILE=minimal.",
        ]
    else:
        status = "warn"
        message = "Rust bridge binary missing — avatar animation will use fallback mode"
        fixes = [
            "This is acceptable in minimal mode.",
            "Switch to PUBCAST_PROFILE=full only on machines meant to run the full avatar bridge.",
        ]
    return DoctorCheck(
        check_id="rust_bridge_binary",
        name="Rust avatar bridge binary",
        status=status,
        required=required,
        message=message,
        detail={"path": str(binary), "exists": exists, "profile": profile},
        fix_instructions=fixes,
    )


def _parse_port(name: str, default: int) -> tuple[int, Optional[str]]:
    raw = os.getenv(name, str(default)).strip()
    try:
        port = int(raw)
    except ValueError:
        return default, f"{name} must be an integer, got: {raw!r}"
    if not (1 <= port <= 65535):
        return default, f"{name} must be between 1 and 65535, got: {port}"
    return port, None


def _is_current_process_owner(owner: Optional[Dict[str, Any]]) -> bool:
    if not owner:
        return False
    return owner.get("pid") == os.getpid()


def _check_default_ports() -> DoctorCheck:
    http_port, http_error = _parse_port("PUBCAST_PORT", 8000)
    rust_port, rust_error = _parse_port("PUBCAST_WS_PORT", 8765)
    ports = {
        "http": http_port,
        "rust_ws": rust_port,
    }

    http_probe = _probe_port("http", ports["http"])
    rust_probe = _probe_port("rust_ws", ports["rust_ws"])

    details = {
        "ports": ports,
        "probes": {
            "http": http_probe.to_dict(),
            "rust_ws": rust_probe.to_dict(),
        },
    }

    fixes: List[str] = []
    status = "pass"

    if http_error or rust_error:
        status = "fail"
        if http_error:
            fixes.append(http_error)
        if rust_error:
            fixes.append(rust_error)

    http_owned_by_self = _is_current_process_owner(http_probe.owner)
    if http_probe.listening and not http_owned_by_self:
        status = "warn" if status != "fail" else status
        http_owner = http_probe.owner or {}
        fixes.append(
            f"If this is not your current PubCast server, stop the process on port {http_probe.port} or set PUBCAST_PORT to a free port."
        )
        if http_owner.get("pid"):
            fixes.append(f"Investigate pid {http_owner['pid']} before launch.")
    elif not http_probe.listening:
        fixes.append(f"Port {http_probe.port} is free for PubCast HTTP, or set PUBCAST_PORT if you prefer another port.")

    if rust_probe.listening:
        rust_owner = rust_probe.owner or {}
        status = "warn" if status != "fail" else status
        fixes.append(
            f"If the Rust bridge is supposed to be external, confirm the listener on port {rust_probe.port} is the expected one."
        )
        if rust_owner.get("pid"):
            fixes.append(f"Rust bridge port owner pid: {rust_owner['pid']}.")
    else:
        fixes.append(f"Rust bridge port {rust_probe.port} is free, which is fine in minimal mode.")

    message_parts = [
        _status_message_for_port(http_probe, expected=True),
        _status_message_for_port(rust_probe, expected=False),
    ]
    if http_owned_by_self:
        message_parts[0] = f"Expected listener on {http_probe.port}: current PubCast process"

    return DoctorCheck(
        check_id="ports",
        name="Default ports",
        status=status,
        required=bool(http_error or rust_error),
        message="; ".join(message_parts),
        detail=details | {"env_errors": [e for e in (http_error, rust_error) if e]},
        fix_instructions=fixes,
    )


def _build_launch_gate(checks: List[DoctorCheck], profile: str) -> Dict[str, Any]:
    blocking_checks = [
        {
            "check_id": c.check_id,
            "name": c.name,
            "message": c.message,
            "fix_instructions": c.fix_instructions,
        }
        for c in checks
        if c.required and c.status == "fail"
    ]
    allowed = not blocking_checks
    reason = "Doctor passed all required launch checks" if allowed else "Doctor found required failures that should block go-live"
    return {
        "allowed": allowed,
        "profile": profile,
        "reason": reason,
        "blocking_checks": blocking_checks,
        "checked_at": time.time(),
    }


def run_doctor(base_dir: Path) -> Dict[str, Any]:
    profile = _current_profile()
    checks = [
        _check_python(),
        _check_core_imports(),
        _check_data_dirs(base_dir),
        _check_write_access(base_dir),
        _check_disk_space(base_dir),
        _check_ffmpeg(),
        _check_sounddevice(),
        _check_rust_bridge_binary(base_dir, profile=profile),
        _check_default_ports(),
    ]

    required_failures = [c for c in checks if c.required and c.status == "fail"]
    warnings = [c for c in checks if c.status == "warn"]

    overall = "ok"
    if required_failures:
        overall = "fail"
    elif warnings:
        overall = "warn"

    launch_gate = _build_launch_gate(checks, profile)

    return {
        "status": overall,
        "profile": profile,
        "timestamp": time.time(),
        "summary": {
            "total": len(checks),
            "passed": sum(1 for c in checks if c.status == "pass"),
            "warnings": len(warnings),
            "failed": sum(1 for c in checks if c.status == "fail"),
            "required_failures": len(required_failures),
        },
        "checks": [c.to_dict() for c in checks],
        "next_steps": _next_steps(checks, profile),
        "launch_gate": launch_gate,
    }


def run_launch_gate(base_dir: Path) -> Dict[str, Any]:
    report = run_doctor(base_dir)
    return report["launch_gate"]


def _next_steps(checks: List[DoctorCheck], profile: str) -> List[str]:
    steps: List[str] = []
    by_id = {c.check_id: c for c in checks}

    for check_id in ("python_version", "core_imports", "data_dirs", "write_access"):
        check = by_id[check_id]
        if check.status == "fail":
            steps.extend(check.fix_instructions[:2])

    if by_id["disk_space"].status == "warn":
        steps.extend(by_id["disk_space"].fix_instructions[:1])
    if by_id["ffmpeg"].status != "pass":
        steps.extend(by_id["ffmpeg"].fix_instructions[:1])
    if by_id["sounddevice"].status != "pass":
        steps.extend(by_id["sounddevice"].fix_instructions[:1])
    if by_id["rust_bridge_binary"].status != "pass":
        if profile == "full":
            steps.extend(by_id["rust_bridge_binary"].fix_instructions[:2])
        else:
            steps.extend(by_id["rust_bridge_binary"].fix_instructions[:1])
    if by_id["ports"].status != "pass":
        steps.extend(by_id["ports"].fix_instructions[:2])

    deduped: List[str] = []
    for step in steps:
        if step and step not in deduped:
            deduped.append(step)
    return deduped


def doctor_json(base_dir: Path) -> str:
    """Optional helper for non-FastAPI integrations that want raw JSON."""
    return json.dumps(run_doctor(base_dir), indent=2)
