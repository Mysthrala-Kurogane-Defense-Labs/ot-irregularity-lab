"""Command line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .evaluation import evaluate
from .simulation import batch, generate_challenge, read_scenario, replay, write_run
from .submission import run_docker_submission, run_submission


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
    dataset_cmd = commands.add_parser("dataset", help="create a seeded dataset from a generation suite")
    dataset_subcommands = dataset_cmd.add_subparsers(dest="dataset_command", required=True)
    create_cmd = dataset_subcommands.add_parser("create", help="generate train/validation/test runs and a manifest")
    create_cmd.add_argument("--suite", type=Path, required=True)
    create_cmd.add_argument("--runs", type=int, required=True)
    create_cmd.add_argument("--seed", type=int, default=42)
    create_cmd.add_argument("--output", type=Path, required=True)
    benchmark_cmd = commands.add_parser("benchmark", help="score model predictions for a generated run")
    benchmark_cmd.add_argument("--run", type=Path, required=True, help="run directory containing ground_truth.json")
    benchmark_cmd.add_argument("--predictions", type=Path, required=True, help="JSONL model output")
    benchmark_cmd.add_argument("--output", type=Path, required=True)
    benchmark_cmd.add_argument("--threshold", type=float, default=0.5)
    benchmark_cmd.add_argument("--overlap", type=float, default=0.1)
    run_cmd = commands.add_parser("run-model", help="run an external command against telemetry only")
    run_cmd.add_argument("--run", type=Path, required=True)
    run_cmd.add_argument("--command", dest="model_command", required=True, help='executable and arguments; use "{input}" and "{output}" placeholders')
    run_cmd.add_argument("--output", type=Path, required=True)
    run_cmd.add_argument("--timeout", type=int, default=300)
    docker_cmd = commands.add_parser("run-container", help="run a Docker submission without network or ground truth mounts")
    docker_cmd.add_argument("--run", type=Path, required=True)
    docker_cmd.add_argument("--image", required=True)
    docker_cmd.add_argument("--output", type=Path, required=True)
    docker_cmd.add_argument("--timeout", type=int, default=300)
    challenge_cmd = commands.add_parser("challenge", help="generate and score a fresh hidden-seed challenge case")
    challenge_cmd.add_argument("--suite", type=Path, required=True)
    challenge_cmd.add_argument("--image", required=True)
    challenge_cmd.add_argument("--output", type=Path, required=True)
    challenge_cmd.add_argument("--timeout", type=int, default=300)
    compare_cmd = commands.add_parser("compare", help="evaluate multiple prediction JSONL files")
    compare_cmd.add_argument("--run", type=Path, required=True)
    compare_cmd.add_argument("--predictions", type=Path, nargs="+", required=True)
    compare_cmd.add_argument("--output", type=Path, required=True)
    compare_cmd.add_argument("--threshold", type=float, default=0.5)
    compare_cmd.add_argument("--overlap", type=float, default=0.1)
    args = parser.parse_args()
    if args.command == "generate":
        scenario = read_scenario(args.scenario)
        metadata = write_run(scenario, args.seed, args.output, csv=args.csv, jsonl=args.jsonl)
        (args.output / "scenario.yaml").write_text(args.scenario.read_text(encoding="utf-8"), encoding="utf-8")
        print(json.dumps(metadata, indent=2))
    elif args.command == "replay":
        print(replay(args.run_dir, args.output))
    elif args.command in {"batch", "dataset"}:
        if args.runs <= 0:
            parser.error("--runs must be positive")
        batch(args.suite, args.runs, args.output, args.seed)
        print(args.output / "dataset_manifest.json")
    elif args.command == "benchmark":
        result = evaluate(args.run / "ground_truth.json", args.predictions, args.output, args.threshold, args.overlap, args.run / "telemetry.parquet", args.run / "run_metadata.json")
        print(json.dumps({key: value for key, value in result.items() if key != "events"}, indent=2))
    elif args.command == "run-model":
        print(run_submission(args.model_command, args.run, args.output, args.timeout))
    elif args.command == "run-container":
        print(run_docker_submission(args.image, args.run, args.output, args.timeout))
    elif args.command == "challenge":
        import tempfile
        args.output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ot-lab-challenge-") as temp:
            case_dir, truth_path = generate_challenge(args.suite, Path(temp))
            predictions = Path(temp) / "predictions.jsonl"
            run_docker_submission(args.image, case_dir, predictions, args.timeout)
            result_dir = Path(temp) / "result"
            result = evaluate(truth_path, predictions, result_dir, telemetry_path=case_dir / "telemetry.parquet", metadata_path=case_dir / "run_metadata.json")
            # Persist only scored output; temporary telemetry, predictions, truth and seed are discarded.
            (args.output / "metrics.json").write_text((result_dir / "metrics.json").read_text(encoding="utf-8"), encoding="utf-8")
            (args.output / "report.html").write_text((result_dir / "report.html").read_text(encoding="utf-8"), encoding="utf-8")
            print(json.dumps({key: value for key, value in result.items() if key != "events"}, indent=2))
    elif args.command == "compare":
        rows = []
        for prediction in args.predictions:
            model_output = args.output / prediction.stem
            metrics = evaluate(args.run / "ground_truth.json", prediction, model_output, args.threshold, args.overlap, args.run / "telemetry.parquet", args.run / "run_metadata.json")
            rows.append({"model": prediction.stem, "precision": metrics["precision"], "recall": metrics["recall"], "f1": metrics["f1"], "pr_auc": metrics["pr_auc"], "false_positives_per_asset_hour": metrics["false_positives_per_asset_hour"], "event_detection_rate": metrics["event_detection_rate"], "percentage_of_event_detected": metrics["percentage_of_event_detected"]})
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "comparison.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
