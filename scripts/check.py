"""One command that runs every check CI runs.

The point is that a contributor does not have to remember seven commands, and
that CI runs the same seven. If a check is only in the workflow file, nobody
runs it locally until it fails on a pull request.

    python scripts/check.py                # everything (backend + frontend)
    python scripts/check.py --backend-only # skip npm
    python scripts/check.py --fast         # format, lint, types (no tests)
    python scripts/check.py --with-db      # also run alembic check
    python scripts/check.py --list         # show the steps and exit

Exit code is 0 only when every step passed. Steps that cannot run because a
tool is missing are reported as SKIP with the reason, never as a pass.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

PYTHON_TARGETS = ["src", "tests", "benchmark", "perf", "evaluation", "migrations"]


@dataclass
class Step:
    name: str
    command: list[str]
    cwd: Path
    #: Set when the step needs something that may be absent locally.
    requires: str | None = None
    detail: str = ""


@dataclass
class Result:
    step: Step
    status: str  # PASS / FAIL / SKIP
    seconds: float
    output: str = ""


def _npm() -> str | None:
    """npm is npm.cmd on Windows; subprocess needs the resolved path."""
    return shutil.which("npm")


def build_steps(*, include_frontend: bool, include_tests: bool, with_db: bool) -> list[Step]:
    python = sys.executable
    steps = [
        Step(
            "format",
            [python, "-m", "ruff", "format", "--check", *PYTHON_TARGETS],
            ROOT,
            detail="ruff format --check",
        ),
        Step(
            "lint",
            [python, "-m", "ruff", "check", *PYTHON_TARGETS],
            ROOT,
            detail="ruff check",
        ),
        Step(
            "types",
            [python, "-m", "mypy"],
            ROOT,
            detail="mypy src + tests",
        ),
    ]

    if include_tests:
        steps.append(
            Step(
                "backend tests",
                [python, "-m", "pytest", "-q"],
                ROOT,
                detail="pytest on SQLite",
            )
        )

    if with_db:
        steps.append(
            Step(
                "migrations",
                [python, "-m", "alembic", "check"],
                ROOT,
                requires="DATABASE_URL pointing at a migrated database",
                detail="alembic check",
            )
        )

    if include_frontend:
        npm = _npm()
        if npm is None:
            steps.append(
                Step(
                    "frontend",
                    [],
                    FRONTEND,
                    requires="node 22+ and npm on PATH",
                    detail="npm lint / test / build",
                )
            )
        else:
            steps.extend(
                [
                    Step("frontend lint", [npm, "run", "lint"], FRONTEND, detail="eslint"),
                    Step("frontend tests", [npm, "test"], FRONTEND, detail="vitest"),
                    Step("frontend build", [npm, "run", "build"], FRONTEND, detail="vite build"),
                ]
            )
    return steps


def run_step(step: Step, *, fail_fast: bool) -> Result:
    if not step.command:
        return Result(step, "SKIP", 0.0, step.requires or "not available")
    if step.requires and not (step.cwd / "node_modules").exists():
        # The only conditional prerequisite here is installed frontend deps.
        return Result(step, "SKIP", 0.0, "run `npm install` in frontend/ first")

    started = time.perf_counter()
    completed = subprocess.run(
        step.command,
        cwd=step.cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    seconds = time.perf_counter() - started
    output = (completed.stdout or "") + (completed.stderr or "")
    return Result(step, "PASS" if completed.returncode == 0 else "FAIL", seconds, output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run every SentinelFlow check.")
    parser.add_argument("--backend-only", action="store_true", help="skip the frontend")
    parser.add_argument("--frontend-only", action="store_true", help="skip Python checks")
    parser.add_argument("--fast", action="store_true", help="skip tests")
    parser.add_argument(
        "--with-db",
        action="store_true",
        help="also run `alembic check` (needs DATABASE_URL)",
    )
    parser.add_argument("--list", action="store_true", help="print the steps and exit")
    parser.add_argument("--fail-fast", action="store_true", help="stop at the first failure")
    args = parser.parse_args(argv)

    include_frontend = not args.backend_only
    include_backend = not args.frontend_only
    steps = build_steps(
        include_frontend=include_frontend,
        include_tests=include_backend and not args.fast,
        with_db=args.with_db and include_backend,
    )
    if not include_backend:
        steps = [step for step in steps if step.name.startswith("frontend")]

    if args.list:
        for step in steps:
            print(f"  {step.name:16} {step.detail}")
        return 0

    results: list[Result] = []
    for step in steps:
        print(f"-> {step.name} ... ", end="", flush=True)
        result = run_step(step, fail_fast=args.fail_fast)
        results.append(result)
        print(f"{result.status}  ({result.seconds:.1f}s)")
        if result.status == "FAIL":
            print()
            print(result.output.rstrip()[-4000:])
            print()
            if args.fail_fast:
                break

    failed = [item for item in results if item.status == "FAIL"]
    skipped = [item for item in results if item.status == "SKIP"]

    print()
    print(f"{'step':18} {'status':6} {'seconds':>8}")
    print("-" * 34)
    for result in results:
        print(f"{result.step.name:18} {result.status:6} {result.seconds:>8.1f}")
        if result.status == "SKIP":
            print(f"{'':18}        {result.output}")

    if failed:
        print()
        print(f"{len(failed)} step(s) failed: {', '.join(item.step.name for item in failed)}")
        return 1
    if skipped:
        print()
        print(f"{len(skipped)} step(s) skipped; see the reasons above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
