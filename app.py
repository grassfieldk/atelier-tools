from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import webbrowser

import uvicorn

from atelier_tools.core import build_index, configure_logging, diagnose, export_csv, installation_dict, search_index
from atelier_tools.server import create_app


def lan_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = result[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def run_web(args: argparse.Namespace) -> int:
    application = create_app()
    config = uvicorn.Config(application, host=args.bind, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    local_url = f"http://127.0.0.1:{args.port}/"
    print(f"Atelier Tools Web UI (この PC): {local_url}")
    if args.bind == "0.0.0.0":
        for address in lan_addresses():
            print(f"Atelier Tools Web UI (LAN): http://{address}:{args.port}/")
    elif not args.bind.startswith("127."):
        print(f"Atelier Tools Web UI (指定アドレス): http://{args.bind}:{args.port}/")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(local_url,)).start()
    server.run()
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Atelier game data explorer")
    subparsers = result.add_subparsers(dest="command")
    web = subparsers.add_parser("web", help="Web UI を起動")
    web.add_argument("--bind", default="0.0.0.0")
    web.add_argument("--port", type=int, default=47831)
    web.add_argument("--no-browser", action="store_true")
    scan = subparsers.add_parser("scan", help="データを抽出")
    scan.add_argument("--game-path")
    search = subparsers.add_parser("search", help="抽出済みデータを検索")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--category", default="all")
    search.add_argument("--language", default="all")
    search.add_argument("--limit", type=int, default=100)
    export = subparsers.add_parser("export", help="CSV を書き出す")
    subparsers.add_parser("diagnose", help="ゲームの配置を検証")
    result.set_defaults(command="web")
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    configure_logging()
    try:
        if args.command == "web":
            return run_web(args)
        if args.command == "scan":
            print(json.dumps(build_index(args.game_path), ensure_ascii=False, indent=2))
        elif args.command == "search":
            print(json.dumps(search_index(args.query, args.category, args.language, args.limit), ensure_ascii=False, indent=2))
        elif args.command == "export":
            print(json.dumps(export_csv(), ensure_ascii=False, indent=2))
        elif args.command == "diagnose":
            diagnosis = diagnose()
            print(json.dumps(installation_dict(diagnosis), ensure_ascii=False, indent=2))
            return 0 if diagnosis.is_valid else 2
        return 0
    except Exception as exception:
        print(f"ERROR: {exception}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
