"""Choose the orchestrator config for this network and print its path.

Two laptops if the WIN service answers, otherwise the tracked config (every job on the M5):
  1. data/config.local.yaml exists and its nodes.win.service answers /health -> use it.
  2. Else resolve discovery.win_hostname (mDNS); if the service answers there, write that
     address into data/config.local.yaml (created from backend/config.yaml) -> use it.
  3. Else -> backend/config.yaml: single-laptop mode, no WIN probes at all. This is the mode
     for a demo away from the WIN laptop (e.g. WIN at home, the Mac at the venue).

Never touches the network beyond the LAN. Progress goes to stderr; only the path to stdout.

    .venv/bin/python scripts/pick_config.py            # prints the config path to use
    .venv/bin/python scripts/pick_config.py --solo     # force single-laptop mode
"""

from __future__ import annotations

import argparse
import concurrent.futures
import socket
import sys
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
TRACKED = ROOT / "backend" / "config.yaml"
LOCAL = ROOT / "data" / "config.local.yaml"


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def healthy(url: str, timeout: float) -> bool:
    try:
        r = httpx.get(f"{url.rstrip('/')}/health", timeout=timeout)
        return r.status_code == 200 and r.json().get("ok") is True
    except Exception:  # noqa: BLE001 - unreachable, refused, not JSON: all mean "no"
        return False


def resolve(hostname: str, timeout: float) -> str | None:
    """IPv4 address for an mDNS name, or None. getaddrinfo can block for seconds; cap it."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(socket.getaddrinfo, hostname, None, socket.AF_INET)
    try:
        infos = fut.result(timeout=timeout)
        return infos[0][4][0] if infos else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def write_local(service_url: str) -> None:
    """data/config.local.yaml = tracked config with nodes.win.service replaced (text edit keeps comments)."""
    text = TRACKED.read_text()
    old = "service: http://WIN_IP:8001}"
    if old not in text:
        raise SystemExit("backend/config.yaml no longer has the WIN_IP placeholder line; update pick_config.py")
    text = text.replace(old, f"service: {service_url}}}  # written by scripts/pick_config.py", 1)
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.write_text("# LOCAL COPY (gitignored), written by scripts/pick_config.py. Do not commit.\n" + text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", action="store_true", help="single-laptop mode, skip WIN checks")
    a = ap.parse_args()
    disc = yaml.safe_load(TRACKED.read_text()).get("discovery", {})
    timeout = float(disc.get("timeout_s", 3))

    if a.solo:
        say("Single-laptop mode (forced): every job runs on the M5.")
        print(TRACKED)
        return 0

    if LOCAL.exists():
        url = yaml.safe_load(LOCAL.read_text())["nodes"]["win"].get("service", "").split("#")[0].strip()
        if "WIN_IP" not in url and healthy(url, timeout):
            write_local(url)  # regenerate from the tracked config so it never goes stale
            say(f"WIN answers at {url}: two-laptop mode ({LOCAL.relative_to(ROOT)}).")
            print(LOCAL)
            return 0
        say(f"WIN does not answer at {url or '(none)'}.")

    host = disc.get("win_hostname")
    if host:
        ip = resolve(host, timeout)
        if ip:
            url = f"http://{ip}:{disc.get('win_port', 8001)}"
            if healthy(url, timeout):
                write_local(url)
                say(f"Found WIN as {host} at {ip}: two-laptop mode (wrote {LOCAL.relative_to(ROOT)}).")
                print(LOCAL)
                return 0
            say(f"{host} resolves to {ip} but its service does not answer.")
        else:
            say(f"{host} does not resolve on this network.")

    say("Single-laptop mode: every job runs on the M5 (WIN not on this network).")
    print(TRACKED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
