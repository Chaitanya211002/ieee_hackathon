"""What the M5 needs to reach this laptop on the network it is on right now.

Run net_info.bat after joining a new network (demo day). It prints this laptop's name and
addresses, checks the WIN service and the firewall rules, and prints the address the M5 needs
for nodes.win.service. Nothing here needs editing when the network changes.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root

from backend.config import get_config  # noqa: E402

SERVICE_PORT, OLLAMA_PORT = 8001, 11434
# Adapters that are not a real local network.
VIRTUAL = ("vethernet", "vmware", "virtualbox", "tailscale", "loopback", "bluetooth", "wsl")


def powershell(script: str) -> str:
    try:
        return subprocess.run(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=20
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def lan_addresses() -> list[tuple[str, str]]:
    """[(ip, adapter)] for real adapters, Windows first, with a portable fallback."""
    raw = powershell(
        "Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,InterfaceAlias | ConvertTo-Json -Compress"
    )
    found: list[tuple[str, str]] = []
    if raw:
        rows = json.loads(raw)
        for row in rows if isinstance(rows, list) else [rows]:
            ip, alias = row["IPAddress"], row["InterfaceAlias"]
            if ip.startswith(("127.", "169.254.")) or any(v in alias.lower() for v in VIRTUAL):
                continue
            found.append((ip, alias))
    if not found:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.connect(("10.255.255.255", 1))  # no packet is sent; this only picks a route
                found.append((s.getsockname()[0], "default route"))
            except OSError:
                pass
    return found


def listening_on_all(port: int) -> bool | None:
    raw = powershell(
        f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue).LocalAddress -join ','"
    )
    if not raw:
        return None
    return any(a in ("0.0.0.0", "::") for a in raw.split(","))


def firewall_rules() -> int | None:
    raw = powershell(
        "(Get-NetFirewallRule -DisplayName 'BenchLog WIN*' -ErrorAction SilentlyContinue | Measure-Object).Count"
    )
    return int(raw) if raw.isdigit() else None


def main() -> int:
    name = f"{socket.gethostname().lower()}.local"
    addrs = lan_addresses()
    coder = get_config()["models"]["coder"]
    todo: list[str] = []

    print("WIN node on this network")
    print(f"  Name       {name}")
    for ip, alias in addrs:
        print(f"  Address    {ip}  ({alias})")
    if not addrs:
        print("  Address    none found: is this laptop connected to a network?")
        todo.append("Connect this laptop to the same network as the M5.")

    try:
        h = requests.get(f"http://127.0.0.1:{SERVICE_PORT}/health", timeout=5).json()
        clients = ", ".join(h["sandbox"]["allowed_clients"])
        print(
            f"  Service    {'ok' if h['ok'] else 'NOT READY'}, speech on {h['speech']['device']}, /run_code for: {clients}"
        )
        if h["speech"]["device"] != "cuda":
            todo.append(
                "Whisper is on the CPU (about 2x slower than real time). Free the GPU and restart: "
                f"ollama stop {coder}, then stop.bat and run.bat."
            )
        if "lan" not in clients and "*" not in clients:
            todo.append(
                "run.bat: set RUN_CODE_CLIENTS=lan (or the M5's IP) and restart, or code jobs fall back to the M5."
            )
    except (requests.RequestException, ValueError, KeyError, TypeError):
        print("  Service    NOT RUNNING")
        todo.append("Start the service: run.bat")

    # Ollama is optional here: the 6 GB card cannot hold Whisper and the coder together, so the
    # coder is meant to run on the M5 (see the README). Report it, but do not ask for it.
    try:
        tags = requests.get(f"http://127.0.0.1:{OLLAMA_PORT}/api/tags", timeout=5).json()
        models = [m["name"] for m in tags.get("models", [])]
        loaded = [
            m["name"]
            for m in requests.get(f"http://127.0.0.1:{OLLAMA_PORT}/api/ps", timeout=5).json().get("models", [])
        ]
        reach = {True: "reachable from the network", False: "this laptop only", None: "reach unknown"}[
            listening_on_all(OLLAMA_PORT)
        ]
        print(f"  Ollama     optional; running, {reach}, {coder} {'present' if coder in models else 'not pulled'}")
        if loaded:
            todo.append(
                f"Ollama has {', '.join(loaded)} loaded, which competes with Whisper for the GPU. "
                f"Unload it (ollama stop {loaded[0]}) unless the coder is meant to run here."
            )
    except (requests.RequestException, ValueError):
        print("  Ollama     optional; not running")

    rules = firewall_rules()
    if rules is not None:
        print(f"  Firewall   {'rules present' if rules >= 2 else 'RULES MISSING'}")
        if rules < 2:
            todo.append("Right-click open_firewall.bat, Run as administrator (once; it covers every network).")

    print("\nOn the M5, nodes.win.service (in data/config.local.yaml, see CLAUDE.md) should be:")
    for ip, _ in addrs:
        print(f"  http://{ip}:{SERVICE_PORT}")
    print(f"or, where the network passes mDNS (on the Mac: ping {name}), the name, which never changes:")
    print(f"  http://{name}:{SERVICE_PORT}")

    if todo:
        print("\nTo do on this laptop:")
        for item in todo:
            print(f"  - {item}")
    else:
        print("\nNothing left to do on this laptop.")
    return 1 if todo else 0


if __name__ == "__main__":
    raise SystemExit(main())
