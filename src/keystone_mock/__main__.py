"""Run the Keystone Core mock: `python -m keystone_mock --port 8765`."""

import argparse

import uvicorn

from .app import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="Keystone Core 7.2 mock (legacy teller workstation)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--idle-timeout", type=float, default=900, help="session idle timeout in seconds")
    args = ap.parse_args()
    uvicorn.run(create_app(idle_timeout_s=args.idle_timeout), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
