"""
Starting the server safely, and diagnosing why it will not start.

    python -m revive serve --open     start (or reuse) the server and open the browser when it is ready
    python -m revive doctor           check Python, packages, model files, port and network in one go

Why this exists: the dashboard is a web page, so it can be open while the Python server is not
running (a restored browser tab, a closed terminal, a crash on start). Every failure mode the
team has met is checked here and explained in plain words.
"""
from __future__ import annotations

import importlib
import json
import platform
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PACKAGES = ["numpy", "pandas", "sklearn", "xgboost", "shap", "pulp", "ifcopenshell", "fastapi",
            "uvicorn", "multipart", "segno", "yaml", "openpyxl", "matplotlib"]


# ------------------------------------------------------------------ port helpers
def port_in_use(port: int) -> bool:
    """True when something already accepts connections on this port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def revive_at(port: int, timeout: float = 1.5) -> dict | None:
    """The /api/ping answer if a REVIVE server is listening on this port, else None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:  # nosec B310 - fixed local URL
            d = json.loads(r.read().decode())
            return d if d.get("app") == "REVIVE" else None
    except Exception:
        return None


def free_port(start: int, tries: int = 20) -> int | None:
    for p in range(start, start + tries):
        if not port_in_use(p):
            return p
    return None


def banner(port: int) -> str:
    from .live import lan_ips
    lines = ["", "=" * 66, "  REVIVE is running.", "",
             f"  Dashboard on this computer:   http://localhost:{port}"]
    ips = lan_ips()
    if ips:
        lines.append(f"  Phones on the same Wi-Fi:     http://{ips[0]}:{port}")
        for ip in ips[1:3]:
            lines.append(f"                     or try:     http://{ip}:{port}")
    lines += ["", "  Keep this window open while you use the app. Close it (or press",
              "  Ctrl+C) to stop the server.", "=" * 66, ""]
    return "\n".join(lines)


def open_when_ready(port: int, open_browser: bool, timeout_s: float = 180) -> None:
    """Wait until the server answers, then print the addresses and (optionally) open the browser.
    Opening only after the server is ready avoids the browser landing on a dead page."""
    def run():
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if revive_at(port, timeout=1.0):
                print(banner(port), flush=True)
                if open_browser:
                    webbrowser.open(f"http://localhost:{port}")
                return
            time.sleep(0.5)
        print(f"\n[REVIVE] The server did not answer on port {port} within {int(timeout_s)} s. "
              "Run  python -m revive doctor  for a diagnosis.\n", flush=True)
    threading.Thread(target=run, daemon=True).start()


def serve(host: str, port: int, reload: bool = False, open_browser: bool = False) -> int:
    import uvicorn
    if port_in_use(port):
        info = revive_at(port)
        if info:
            print(f"\n[REVIVE] REVIVE {info.get('version', '')} is already running on port {port}. "
                  f"Using that server: http://localhost:{port}\n", flush=True)
            if open_browser:
                webbrowser.open(f"http://localhost:{port}")
            return 0
        alt = free_port(port + 1)
        if alt is None:
            print(f"[REVIVE] Port {port} and the next 20 ports are busy. Close the program using them, "
                  "or start with  --port 9000", flush=True)
            return 1
        print(f"\n[REVIVE] Port {port} is used by another program, so REVIVE will use port {alt}.\n", flush=True)
        port = alt
    open_when_ready(port, open_browser)
    try:
        uvicorn.run("revive.server:app", host=host, port=port, reload=reload, workers=1,
                    timeout_graceful_shutdown=2)
    except OSError as exc:  # e.g. a race for the port, or a host the OS refuses
        print(f"\n[REVIVE] The server could not start: {exc}\nRun  python -m revive doctor  for a diagnosis.\n",
              flush=True)
        return 1
    return 0


# ------------------------------------------------------------------ doctor
def doctor(port: int = 8000) -> int:
    from .config import ROOT, load_config, path
    rows: list[tuple[str, str, str]] = []

    def add(state, item, detail):
        rows.append((state, item, detail))

    v = sys.version_info
    py_ok = (3, 12) <= v[:2] <= (3, 14)
    state = "OK" if py_ok else "WARN" if v[:2] == (3, 11) or v[:2] > (3, 14) else "FAIL"
    note = "" if py_ok else ("  (works with slightly older packages; 3.12 recommended)" if v[:2] == (3, 11)
                             else "  (not tested; use 3.12, 3.13 or 3.14)" if v[:2] > (3, 14) else "  (too old: install 3.12)")
    add(state, "Python", f"{platform.python_version()} at {sys.executable}{note}")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    add("OK" if in_venv else "WARN", "Virtual environment",
        sys.prefix if in_venv else "not active: run setup.bat / ./setup.sh, then run.bat / ./run.sh")

    missing = []
    for name in PACKAGES:
        try:
            m = importlib.import_module(name)
            ver = getattr(m, "__version__", "")
            if name == "pulp":
                from .optimizer import _solver
                sv = _solver()
                if sv is None or not sv.available():
                    add("FAIL", "package pulp", f"{ver}: the CBC solver is missing (pip install \"pulp>=2.7,<3\")")
                    continue
                ver += ", CBC solver available"
            add("OK", f"package {name}", ver)
        except Exception as exc:
            missing.append(name)
            add("FAIL", f"package {name}", f"{type(exc).__name__}: {exc}")

    try:
        cfg = load_config()
        add("OK", "config/config.yaml", "loaded")
    except Exception as exc:
        add("FAIL", "config/config.yaml", str(exc))
        cfg = None
    if cfg:
        clean = path(cfg["data"]["clean_file"])
        add("OK" if clean.exists() else "FAIL", "dataset", str(clean.relative_to(ROOT)) if clean.exists()
            else f"missing {clean}: put the workbook in data/raw and run  python -m revive setup")
        card = ROOT / "models" / "model_card.json"
        add("OK" if card.exists() else "FAIL", "trained models",
            "models/model_card.json" if card.exists() else "missing: run  python -m revive train")
        ifc = path(cfg["bim"]["ifc_file"])
        add("OK" if ifc.exists() else "WARN", "demo IFC model", ifc.name if ifc.exists()
            else "missing (optional): python -m revive sample-ifc")
    if not missing and cfg:
        try:
            from .inference import get_predictor
            P = get_predictor()
            add("OK", "model loads", f"{len(P.gates)} checkpoints, trained {str(P.card.get('trained_at', ''))[:10]}")
        except Exception as exc:
            add("FAIL", "model loads", f"{type(exc).__name__}: {exc}")

    if port_in_use(port):
        info = revive_at(port)
        add("OK" if info else "WARN", f"port {port}",
            f"REVIVE {info.get('version')} is running: http://localhost:{port}" if info
            else "used by another program; REVIVE will pick the next free port")
    else:
        add("INFO", f"port {port}", "free (REVIVE is not running right now)")

    try:
        from .live import lan_ips
        ips = lan_ips()
        add("OK" if ips else "WARN", "phone link address",
            ", ".join(f"http://{ip}:{port}" for ip in ips) if ips else "no network found: phones cannot connect")
    except Exception as exc:
        add("WARN", "phone link address", str(exc))
    if platform.system() == "Windows":
        add("INFO", "Windows firewall", "if the phone cannot open the link, run phone-access.bat once (as administrator)")

    try:
        urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?latitude=33.7&longitude=73.0&daily=rain_sum",  # nosec B310
                               timeout=4)
        add("OK", "internet (live weather)", "reachable")
    except Exception:
        add("INFO", "internet (live weather)", "not reachable: the app still works, weather is entered by hand")

    width = max(len(r[1]) for r in rows) + 2
    print("\nREVIVE doctor\n" + "-" * 72)
    for state, item, detail in rows:
        print(f"  {state:<5} {item:<{width}} {detail}")
    print("-" * 72)
    fails = [r for r in rows if r[0] == "FAIL"]
    if fails:
        print(f"{len(fails)} problem(s) found. Fix the FAIL lines above, top to bottom.")
        if missing:
            print("Missing packages: run setup.bat (Windows) or ./setup.sh, which reinstalls them.")
    else:
        print("No blocking problems. Start the app with run.bat / ./run.sh  (python -m revive serve --open).")
    print()
    return 1 if fails else 0
