"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import math
import sys
import zipfile
from pathlib import Path

from . import __version__
from .calibration import (
    write_bosch_cnc_analysis,
    write_metropt_analysis,
    write_zema_hydraulic_analysis,
)
from .datasets import package_dataset, verify_dataset_package
from .evaluation import aggregate_challenge_metrics, evaluate, write_challenge_report
from .simulation import batch, generate_challenge, read_scenario, replay, write_run
from .submission import DEFAULT_MAX_OUTPUT_BYTES, run_docker_submission, run_submission


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
    batch_cmd.add_argument("--workers", type=int, default=1, help="parallel run-generation processes (default: 1)")
    dataset_cmd = commands.add_parser("dataset", help="create, package, or verify a dataset")
    dataset_subcommands = dataset_cmd.add_subparsers(dest="dataset_command", required=True)
    create_cmd = dataset_subcommands.add_parser("create", help="generate train/validation/test runs and a manifest")
    create_cmd.add_argument("--suite", type=Path, required=True)
    create_cmd.add_argument("--runs", type=int, required=True)
    create_cmd.add_argument("--seed", type=int, default=42)
    create_cmd.add_argument("--output", type=Path, required=True)
    create_cmd.add_argument("--resume", action="store_true", help="keep per-run checkpoints and resume after interruption")
    create_cmd.add_argument("--workers", type=int, default=1, help="parallel run-generation processes (default: 1)")
    package_cmd = dataset_subcommands.add_parser("package", help="create deterministic, separate ZIP artifacts for public partitions")
    package_cmd.add_argument("--dataset", type=Path, required=True)
    package_cmd.add_argument("--dataset-version", required=True, help="public dataset release version, for example 0.4.0")
    package_cmd.add_argument("--data-license", required=True, help="license identifier, for example CC-BY-4.0 or CC0-1.0")
    package_cmd.add_argument("--license-file", type=Path, required=True, help="full data license notice to include with each artifact")
    package_cmd.add_argument("--partition", dest="partitions", nargs="+", choices=("train", "validation", "test"))
    package_cmd.add_argument("--output", type=Path, required=True, help="new directory for per-partition ZIPs and release manifest")
    verify_cmd = dataset_subcommands.add_parser("verify", help="verify a packaged release's checksums and telemetry/label separation")
    verify_cmd.add_argument("--release", type=Path, required=True, help="release directory produced by `ot-lab dataset package`")
    verify_cmd.add_argument("--json", action="store_true", help="print a machine-readable verification report")
    calibration_cmd = commands.add_parser("calibration", help="analyze public reference data locally; source records are not copied")
    calibration_sub = calibration_cmd.add_subparsers(dest="calibration_command", required=True)
    metropt_cmd = calibration_sub.add_parser("analyze-metropt", help="summarize MetroPT-3 compressor modes and cadence")
    metropt_cmd.add_argument("--input", type=Path, required=True, help="locally obtained MetroPT3(AirCompressor).csv")
    metropt_cmd.add_argument("--output", type=Path, required=True, help="aggregate JSON report path")
    hydraulic_cmd = calibration_sub.add_parser("analyze-hydraulic", help="summarize UCI ZeMA hydraulic test-rig cycles by condition")
    hydraulic_cmd.add_argument("--input", type=Path, required=True, help="locally obtained UCI dataset 447 ZIP archive")
    hydraulic_cmd.add_argument("--output", type=Path, required=True, help="aggregate JSON report path")
    bosch_cmd = calibration_sub.add_parser("analyze-bosch-cnc", help="summarize Bosch CNC acceleration RMS by process group")
    bosch_cmd.add_argument("--input-dir", type=Path, required=True, help="locally obtained Bosch CNC data directory")
    bosch_cmd.add_argument("--source-revision", help="Git commit of the source dataset for provenance")
    bosch_cmd.add_argument("--output", type=Path, required=True, help="aggregate JSON report path")
    benchmark_cmd = commands.add_parser("benchmark", help="score model predictions for a generated run")
    benchmark_cmd.add_argument("--run", type=Path, required=True, help="run directory containing ground_truth.json")
    benchmark_cmd.add_argument("--predictions", type=Path, required=True, help="JSONL model output")
    benchmark_cmd.add_argument("--output", type=Path, required=True)
    benchmark_cmd.add_argument("--threshold", type=float, default=0.5)
    benchmark_cmd.add_argument("--overlap", type=float, default=0.1)
    benchmark_cmd.add_argument("--alert-merge-gap-seconds", type=float, default=0.0, help="merge thresholded alert windows separated by at most this gap")
    run_cmd = commands.add_parser("run-model", help="run a trusted local command against telemetry only; this is not a security sandbox")
    run_cmd.add_argument("--run", type=Path, required=True)
    run_cmd.add_argument("--command", dest="model_command", required=True, help='executable and arguments; use "{input}" and "{output}" placeholders')
    run_cmd.add_argument("--output", type=Path, required=True)
    run_cmd.add_argument("--timeout", type=int, default=300)
    run_cmd.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    docker_cmd = commands.add_parser("run-container", help="run a Docker submission without network or ground truth mounts")
    docker_cmd.add_argument("--run", type=Path, required=True)
    docker_cmd.add_argument("--image", required=True)
    docker_cmd.add_argument("--output", type=Path, required=True)
    docker_cmd.add_argument("--timeout", type=int, default=300)
    docker_cmd.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    challenge_cmd = commands.add_parser("challenge", help="generate and score fresh hidden-seed challenge cases")
    challenge_cmd.add_argument("--suite", type=Path, required=True)
    challenge_cmd.add_argument("--challenge-suite", type=Path, help="optional independently versioned hidden-case distribution")
    challenge_cmd.add_argument("--image", required=True)
    challenge_cmd.add_argument("--output", type=Path, required=True)
    challenge_cmd.add_argument("--timeout", type=int, default=300)
    challenge_cmd.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    challenge_cmd.add_argument("--cases", type=int, default=1, help="number of independent hidden cases to run (default: 1)")
    challenge_cmd.add_argument("--threshold", type=float, default=0.5)
    challenge_cmd.add_argument("--overlap", type=float, default=0.1)
    challenge_cmd.add_argument("--alert-merge-gap-seconds", type=float, default=0.0)
    opcua_cmd = commands.add_parser("opcua-replay", help="serve canonical telemetry over optional OPC UA adapter (loopback by default)")
    opcua_cmd.add_argument("--telemetry", type=Path, required=True)
    opcua_cmd.add_argument("--endpoint", default="opc.tcp://127.0.0.1:4840/ot-lab/")
    opcua_cmd.add_argument("--fast", action="store_true", help="replay immediately without matching timestamp intervals")
    opcua_cmd.add_argument("--serve", action="store_true", help="keep the server running with the final values after replay")
    modbus_cmd = commands.add_parser("modbus-replay", help="serve canonical telemetry over optional Modbus/TCP (loopback by default)")
    modbus_cmd.add_argument("--telemetry", type=Path, required=True)
    modbus_cmd.add_argument("--host", default="127.0.0.1")
    modbus_cmd.add_argument("--port", type=int, default=5020)
    modbus_cmd.add_argument("--device-id", type=int, default=1)
    modbus_cmd.add_argument("--fast", action="store_true", help="replay immediately without matching timestamp intervals")
    modbus_cmd.add_argument("--serve", action="store_true", help="keep the server running with the final values after replay")
    compare_cmd = commands.add_parser("compare", help="evaluate multiple prediction JSONL files")
    compare_cmd.add_argument("--run", type=Path, required=True)
    compare_cmd.add_argument("--predictions", type=Path, nargs="+", required=True)
    compare_cmd.add_argument("--output", type=Path, required=True)
    compare_cmd.add_argument("--threshold", type=float, default=0.5)
    compare_cmd.add_argument("--overlap", type=float, default=0.1)
    compare_cmd.add_argument("--alert-merge-gap-seconds", type=float, default=0.0, help="merge thresholded alert windows separated by at most this gap")
    args = parser.parse_args()
    if args.command == "generate":
        scenario = read_scenario(args.scenario)
        metadata = write_run(scenario, args.seed, args.output, csv=args.csv, jsonl=args.jsonl)
        (args.output / "scenario.yaml").write_text(args.scenario.read_text(encoding="utf-8"), encoding="utf-8")
        print(json.dumps(metadata, indent=2))
    elif args.command == "replay":
        print(replay(args.run_dir, args.output))
    elif args.command in {"batch", "dataset"} and (args.command == "batch" or args.dataset_command == "create"):
        if args.runs <= 0:
            parser.error("--runs must be positive")
        batch(args.suite, args.runs, args.output, args.seed, resume=getattr(args, "resume", False), workers=args.workers)
        print(args.output / "dataset_manifest.json")
    elif args.command == "dataset" and args.dataset_command == "package":
        print(package_dataset(args.dataset, args.dataset_version, args.output, args.license_file, args.data_license, args.partitions))
    elif args.command == "dataset" and args.dataset_command == "verify":
        try:
            report = verify_dataset_package(args.release)
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, EOFError) as error:
            print(f"ot-lab: dataset verification failed: {error}", file=sys.stderr)
            raise SystemExit(1) from None
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(
                f"Verified {report['dataset_id']} v{report['dataset_version']}: "
                f"{len(report['partitions'])} partition(s), checksums and archive CRCs valid; labels are separate."
            )
    elif args.command == "calibration":
        if args.calibration_command == "analyze-metropt":
            print(write_metropt_analysis(args.input, args.output))
        elif args.calibration_command == "analyze-hydraulic":
            print(write_zema_hydraulic_analysis(args.input, args.output))
        elif args.calibration_command == "analyze-bosch-cnc":
            print(write_bosch_cnc_analysis(args.input_dir, args.output, args.source_revision))
    elif args.command == "benchmark":
        result = evaluate(args.run / "ground_truth.json", args.predictions, args.output, args.threshold, args.overlap, args.run / "telemetry.parquet", args.run / "run_metadata.json", args.alert_merge_gap_seconds)
        print(json.dumps({key: value for key, value in result.items() if key != "events"}, indent=2))
    elif args.command == "run-model":
        print(run_submission(args.model_command, args.run, args.output, args.timeout, args.max_output_bytes))
    elif args.command == "run-container":
        print(run_docker_submission(args.image, args.run, args.output, args.timeout, args.max_output_bytes))
    elif args.command == "challenge":
        import tempfile
        if args.cases <= 0:
            parser.error("--cases must be positive")
        if not math.isfinite(args.threshold) or not 0 <= args.threshold <= 1:
            parser.error("--threshold must be between 0 and 1")
        if not math.isfinite(args.overlap) or not 0 <= args.overlap <= 1:
            parser.error("--overlap must be between 0 and 1")
        if not math.isfinite(args.alert_merge_gap_seconds) or args.alert_merge_gap_seconds < 0:
            parser.error("--alert-merge-gap-seconds must be a finite non-negative number")
        case_metrics = []
        with tempfile.TemporaryDirectory(prefix="ot-lab-challenge-") as temp:
            temp_path = Path(temp)
            for index in range(args.cases):
                case_root = temp_path / f"case-{index:05d}"
                case_dir, truth_path = generate_challenge(args.suite, case_root, challenge_suite_path=args.challenge_suite)
                predictions = case_root / "predictions.jsonl"
                run_docker_submission(args.image, case_dir, predictions, args.timeout, args.max_output_bytes)
                result = evaluate(
                    truth_path, predictions, case_root / "result", args.threshold, args.overlap,
                    case_dir / "telemetry.parquet", case_dir / "run_metadata.json", args.alert_merge_gap_seconds,
                )
                case_metrics.append({
                    key: result[key] for key in (
                        "metric_version", "threshold", "overlap_threshold", "alert_merge_gap_seconds",
                        "event_count", "true_positive_events", "alert_episode_count", "false_positive_windows",
                        "exposure_asset_hours", "false_positive_duration_s", "window_true_positives",
                        "window_false_positives", "window_false_negatives", "expected_sample_count",
                        "mean_event_coverage", "mean_time_to_first_detection_s", "pr_auc", "event_type_metrics",
                    )
                })
            aggregate = aggregate_challenge_metrics(case_metrics)
            # Persist only pooled metrics. Temporary predictions, event rows, telemetry, ground truth and seeds are discarded.
            write_challenge_report(aggregate, args.output)
        print(json.dumps(aggregate, indent=2))
    elif args.command == "opcua-replay":
        import asyncio

        from .protocols.opcua import replay_opcua

        asyncio.run(replay_opcua(args.telemetry, args.endpoint, realtime=not args.fast, stay_open=args.serve))
    elif args.command == "modbus-replay":
        import asyncio

        from .protocols.modbus import replay_modbus

        asyncio.run(replay_modbus(args.telemetry, args.host, args.port, args.device_id, realtime=not args.fast, stay_open=args.serve))
    elif args.command == "compare":
        rows = []
        summary_keys = (
            "metric_version", "threshold", "overlap_threshold", "alert_merge_gap_seconds",
            "precision", "recall", "f1", "event_precision", "event_recall", "event_f1",
            "pr_auc", "window_precision", "window_recall", "window_f1", "window_pr_auc",
            "event_count", "true_positive_events", "missed_events", "event_detection_rate",
            "alert_episode_count", "false_positive_alert_episodes",
            "false_positive_alert_episodes_per_asset_hour", "false_positive_windows",
            "false_positives_per_asset_hour", "false_positives_per_asset_day",
            "false_positive_duration_s", "exposure_asset_hours", "mean_event_coverage",
            "percentage_of_event_detected", "mean_time_to_first_detection_s",
            "mean_detection_latency_s", "event_type_metrics",
        )
        for prediction in args.predictions:
            model_output = args.output / prediction.stem
            metrics = evaluate(args.run / "ground_truth.json", prediction, model_output, args.threshold, args.overlap, args.run / "telemetry.parquet", args.run / "run_metadata.json", args.alert_merge_gap_seconds)
            rows.append({"model": prediction.stem, **{key: metrics[key] for key in summary_keys}})
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "comparison.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
