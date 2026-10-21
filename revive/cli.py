"""
Command line:
    python -m revive setup                 ingest + train + sample IFC (first run)
    python -m revive ingest [--file X]     raw workbook -> data/processed/projects_clean.csv
    python -m revive train [--tune] [--sensitivity]
    python -m revive evaluate --file X     score NEW projects as an external test set
    python -m revive sample-ifc            regenerate the illustrative IFC model
    python -m revive serve [--port 8000] [--open]
    python -m revive doctor                diagnose why the app or the phone link does not work
    python -m revive create-company        add a company and its admin (works when web sign-up is closed)
    python -m revive reset-password        set a new password for a user (signs them out everywhere)
    python -m revive admin-link [--open]   one-time sign-in link for an admin (no password; console = proof)
"""
from __future__ import annotations

import argparse
import sys
import warnings


def main(argv=None) -> int:
    warnings.filterwarnings("ignore", category=UserWarning)
    ap = argparse.ArgumentParser(prog="revive", description="REVIVE AI-BIM delay early warning")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="first-run setup")
    p = sub.add_parser("ingest", help="clean and anonymise the survey workbook")
    p.add_argument("--file")
    p.add_argument("--sheet")
    p = sub.add_parser("train", help="train, cross-validate and save models")
    p.add_argument("--tune", action="store_true", help="small grid search on the time model")
    p.add_argument("--no-compare", action="store_true", help="skip RF/SVM/linear comparison")
    p.add_argument("--sensitivity", action="store_true", help="also run the data-scope sensitivity check")
    p = sub.add_parser("evaluate", help="external test on new projects")
    p.add_argument("--file", required=True)
    p.add_argument("--sheet")
    p = sub.add_parser("sample-ifc", help="regenerate the illustrative IFC model")
    p.add_argument("--out")
    p = sub.add_parser("serve", help="start the web app")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--reload", action="store_true")
    p.add_argument("--open", action="store_true", help="open the browser")
    p = sub.add_parser("doctor", help="check Python, packages, models, port and network")
    p.add_argument("--port", type=int, default=None)
    p = sub.add_parser("create-company", help="add a company workspace and its admin user")
    p.add_argument("--company", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p = sub.add_parser("reset-password", help="set a new password for a user")
    p.add_argument("--email", required=True)
    p = sub.add_parser("admin-link", help="print a one-time sign-in link for an admin (valid 10 minutes, single use)")
    p.add_argument("--email", help="which admin (needed only when there is more than one)")
    p.add_argument("--minutes", type=float, default=10, help="how long the link stays valid (1-60, default 10)")
    p.add_argument("--open", action="store_true", help="open the link in this computer's browser")
    a = ap.parse_args(argv)

    if a.cmd == "setup":
        from .pipeline import bootstrap
        bootstrap(verbose=True)
        print("Setup complete. Start the app with:  python -m revive serve --open")
    elif a.cmd == "ingest":
        from .data import ingest
        df, q = ingest(a.file, a.sheet)
        print(f"{q['rows']} rows, {q['rows_with_time_target']} with a time outcome, "
              f"{q['hypothetical_rows']} hypothetical. Unmatched answers: {q['unmatched_answers'] or 'none'}")
    elif a.cmd == "train":
        from .modeling import sensitivity, train
        train(compare=not a.no_compare, tune=a.tune)
        if a.sensitivity:
            sensitivity()
    elif a.cmd == "evaluate":
        from .evaluate import evaluate_external
        res = evaluate_external(a.file, a.sheet)
        print(res["metrics"])
        print("Full table written to reports/external_test_*.csv")
    elif a.cmd == "sample-ifc":
        from .config import load_config, path
        from .sample_ifc import build
        print(build(a.out or path(load_config()["bim"]["ifc_file"])))
    elif a.cmd == "serve":
        import os
        from .config import load_config
        from .launcher import serve
        cfg = load_config()["app"]
        host = a.host or os.environ.get("HOST", cfg["host"])
        port = a.port or int(os.environ.get("PORT", cfg["port"]))
        return serve(host, port, reload=a.reload, open_browser=a.open)
    elif a.cmd in ("create-company", "reset-password"):
        import getpass
        from . import auth
        pw = getpass.getpass("New password (10+ characters, not shown): ")
        if pw != getpass.getpass("Repeat it: "):
            print("The passwords do not match.")
            return 1
        try:
            if a.cmd == "create-company":
                u = auth.register_company(a.company, a.name, a.email, pw)
                print(f"Company '{u['company_name']}' created. {u['email']} is its admin.")
            else:
                u = auth.user_by_email(a.email)
                if not u:
                    print("No user with that e-mail.")
                    return 1
                auth.set_password(u["id"], pw)
                print("Password changed; that user is signed out on every device.")
        except auth.AuthError as exc:
            print(exc)
            return 1
    elif a.cmd == "admin-link":
        import os
        import webbrowser
        from . import auth
        from .config import load_config
        from .launcher import revive_at
        try:
            token, u = auth.create_admin_link(a.email, a.minutes)
        except auth.AuthError as exc:
            print(exc)
            return 1
        start = int(os.environ.get("PORT", load_config()["app"]["port"]))
        port = next((p for p in range(start, start + 20) if revive_at(p, timeout=0.6)), None)
        url = f"http://localhost:{port or start}/auth/link/{token}"
        mins = max(1, min(60, round(a.minutes)))
        print(f"\n  One-time admin sign-in for {u['name']} <{u['email']}>, {u['company_name']}\n\n  {url}\n")
        print(f"  Open it on this computer within {mins} minutes. It works once; after that, run this command again.")
        print("  Do not send it to anyone: whoever opens it first is signed in as this admin.")
        if port is None:
            print(f"  Note: REVIVE is not answering on port {start}. Start it (run.bat) before opening the link.")
        if a.open:
            webbrowser.open(url)
    elif a.cmd == "doctor":
        import os
        from .config import load_config
        from .launcher import doctor
        return doctor(a.port or int(os.environ.get("PORT", load_config()["app"]["port"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
