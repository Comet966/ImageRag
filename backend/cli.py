"""Reproducible CLI for preparing the desktop application's shared index."""

import argparse
import json

from backend.core import ROOT, SearchService, ServiceError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status", "index", "search"])
    parser.add_argument("query", nargs="?")
    args = parser.parse_args()
    service = SearchService()
    try:
        if args.command == "status":
            result = service.status()
        elif args.command == "index":
            result = service.index(lambda event: print(f"入库 {event['done']}/{event['total']}", flush=True))
            report = ROOT / "outputs" / "index-run.json"
            report.parent.mkdir(exist_ok=True)
            report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            result = service.search(args.query or "", limit=5)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ServiceError as exc:
        parser.exit(1, f"{exc}\n")
    finally:
        service.close()


if __name__ == "__main__":
    main()
