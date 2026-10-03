"""Command line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .models import Scenario
from .simulation import batch, read_scenario, replay, write_run


def main() -> None:
    parser = argparse.ArgumentParser(prog="ot-lab", description="Generate reproducible synthetic OT telemetry")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="generate one scenario run")
    generate.add_argument("--scenario", type=Path, required=True)
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--csv", action="store_true")
    generate.add_argument("--jsonl", action="store_true")
    replay_cmd = commands.add_parser("replay", help="recreate a run from saved scenario and seed")
    replay_cmd.add_argument("run_dir", type=Path)
    replay_cmd.add_argument("--output", type=Path)
    batch_cmd = commands.add_parser("batch", help="generate independent seeded partitions")
    batch_cmd.add_argument("--suite", type=Path, required=True)
    batch_cmd.add_argument("--runs", type=int, required=True)
    batch_cmd.add_argument("--seed", type=int, default=42)
    batch_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        scenario = read_scenario(args.scenario)
        metadata = write_run(scenario, args.seed, args.output, csv=args.csv, jsonl=args.jsonl)
        (args.output / "scenario.yaml").write_text(args.scenario.read_text(encoding="utf-8"), encoding="utf-8")
        print(json.dumps(metadata, indent=2))
    elif args.command == "replay":
        print(replay(args.run_dir, args.output))
    elif args.command == "batch":
        if args.runs <= 0:
            parser.error("--runs must be positive")
        batch(args.suite, args.runs, args.output, args.seed)
        print(args.output / "dataset_manifest.json")


if __name__ == "__main__":
    main()
