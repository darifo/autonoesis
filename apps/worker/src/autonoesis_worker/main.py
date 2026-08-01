"""Worker process bootstrap."""

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonoesis durable execution worker")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the bootstrap without connecting to Temporal",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.check:
        print("autonoesis-worker bootstrap: ok")
        return 0
    print("Temporal workflow registration will be added with the first vertical slice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
