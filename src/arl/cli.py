"""Offline-first command-line interface for Agent Reliability Lab."""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import sys
from pathlib import Path
from typing import Any

from arl import __version__
from arl.analysis.paired import analyze_paired_outcomes
from arl.core.types import canonical_json
from arl.evidence.migrate import build_public_bundle, v029_public_evidence_status
from arl.evidence.verify import verify_bundle
from arl.registry import claims, studies
from arl.studies.budget import v029_budget_diagnostic
from arl.studies.smoke import run_smoke


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _project_root() -> Path | None:
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src/arl").is_dir():
            return candidate
    return None


def doctor_report() -> dict[str, Any]:
    """Run local installation and repository diagnostics without network access."""

    required_imports = [
        "arl.analysis",
        "arl.evidence",
        "arl.studies",
        "arl.cli",
    ]
    imports: dict[str, bool] = {}
    for name in required_imports:
        try:
            __import__(name)
            imports[name] = True
        except Exception:
            imports[name] = False
    root = _project_root()
    repository: dict[str, Any]
    if root is None:
        repository = {
            "state": "not_applicable_installed_wheel",
            "required_files": None,
            "historical_release_bundle": None,
            "v029_public_evidence": "NOT_MATERIALIZED_OR_NOT_IN_CHECKOUT",
        }
    else:
        required = [
            "README.md",
            "README.zh-CN.md",
            "pyproject.toml",
            "schemas/arl-evidence-v1/manifest.schema.json",
            "docs/claims-registry.md",
        ]
        required_result = {name: (root / name).is_file() for name in required}
        bundle_root = root / "artifacts/release_bundle_v15"
        bundle_result: dict[str, Any]
        try:
            from arl_release.bundles import verify_bundle_dir

            bundle_result = {"state": "verified", **verify_bundle_dir(bundle_root)}
        except Exception as error:
            bundle_result = {"state": "failed", "error": f"{type(error).__name__}: {error}"}
        repository = {
            "state": "repository_checkout",
            "root": str(root),
            "required_files": required_result,
            "historical_release_bundle": bundle_result,
            "v029_public_evidence": v029_public_evidence_status(root),
        }
    valid = all(imports.values())
    if root is not None:
        valid = valid and all(repository["required_files"].values())
        valid = valid and repository["historical_release_bundle"]["state"] == "verified"
    return {
        "package": "agent-reliability-lab",
        "package_version": __version__,
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "network_calls": 0,
        "provider_calls": 0,
        "imports": imports,
        "repository": repository,
        "valid": valid,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arl",
        description=(
            "Fault-injection benchmark and reliability runtime for stateful tool-using agents."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check the local installation offline")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    run = subparsers.add_parser("run", help="run a local study")
    run_subparsers = run.add_subparsers(dest="run_command", required=True)
    smoke = run_subparsers.add_parser("smoke", help="run the no-provider synthetic smoke study")
    smoke.add_argument("--output", type=Path, help="new output directory; defaults to a temp dir")

    verify = subparsers.add_parser("verify", help="verify a public evidence bundle offline")
    verify.add_argument("bundle", type=Path)
    verify.add_argument("--json", action="store_true", help="emit the complete report")

    analyze = subparsers.add_parser("analyze", help="analyze only a verified public ledger")
    analyze.add_argument("bundle", type=Path)
    analyze.add_argument("--bootstrap-seed", type=int, default=20260821)
    analyze.add_argument("--iterations", type=int, default=2000)
    analyze.add_argument("--output", type=Path, help="write canonical JSON to a new file")

    bundle = subparsers.add_parser("bundle", help="publish reviewed normalized private evidence")
    bundle.add_argument("private_study_dir", type=Path)
    bundle.add_argument("--public-output", type=Path, required=True)
    bundle.add_argument(
        "--public-state-field",
        action="append",
        required=True,
        help="explicitly allow one synthetic state field; repeat as needed",
    )

    claims_parser = subparsers.add_parser("claims", help="show the claim registry")
    claims_parser.add_argument("--json", action="store_true")
    studies_parser = subparsers.add_parser("studies", help="show study status")
    studies_parser.add_argument("--json", action="store_true")

    budget = subparsers.add_parser("budget-diagnostic", help="show the read-only v0.29 cap audit")
    budget.add_argument("--json", action="store_true")
    return parser


def _write_new_json(path: Path, value: Any) -> None:
    payload = (canonical_json(value) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)


def _print_registry(records: list[dict[str, Any]], *, identifier: str) -> None:
    for record in records:
        status = record.get("claim_status", record.get("status", "unknown"))
        print(f"{record[identifier]}\t{status}")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            report = doctor_report()
            if args.json:
                _print_json(report)
            else:
                print(
                    f"ARL {report['package_version']} | Python {report['python']} | "
                    f"SQLite {report['sqlite']} | offline checks: "
                    f"{'PASS' if report['valid'] else 'FAIL'}"
                )
            return 0 if report["valid"] else 1
        if args.command == "run" and args.run_command == "smoke":
            _print_json(run_smoke(args.output))
            return 0
        if args.command == "verify":
            verification_report = verify_bundle(args.bundle)
            if args.json:
                _print_json(verification_report.as_dict())
            else:
                print(
                    f"{'VALID' if verification_report.valid else 'INVALID'}: "
                    f"{verification_report.bundle}"
                )
                for error in verification_report.errors:
                    print(f"  {error}", file=sys.stderr)
            return 0 if verification_report.valid else 1
        if args.command == "analyze":
            verification = verify_bundle(args.bundle)
            if not verification.valid:
                for error in verification.errors:
                    print(error, file=sys.stderr)
                return 1
            from arl.evidence.bundle import load_bundle

            public = load_bundle(args.bundle)
            result = analyze_paired_outcomes(
                public["episodes"],
                bootstrap_seed=args.bootstrap_seed,
                bootstrap_iterations=args.iterations,
            )
            if args.output:
                _write_new_json(args.output, result)
                print(args.output.resolve())
            else:
                _print_json(result)
            return 0
        if args.command == "bundle":
            output = build_public_bundle(
                args.private_study_dir,
                args.public_output,
                public_state_fields=args.public_state_field,
            )
            verification = verify_bundle(output)
            if not verification.valid:
                raise ValueError(f"generated bundle failed verification: {verification.errors}")
            print(output.resolve())
            return 0
        if args.command == "claims":
            records = claims()
            _print_json(records) if args.json else _print_registry(records, identifier="claim_id")
            return 0
        if args.command == "studies":
            records = studies()
            _print_json(records) if args.json else _print_registry(records, identifier="study_id")
            return 0
        if args.command == "budget-diagnostic":
            report = v029_budget_diagnostic()
            _print_json(report) if args.json else _print_json(report)
            return 0
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"arl: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
