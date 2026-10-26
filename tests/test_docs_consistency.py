"""Docs that describe the system must keep describing the system.

Every endpoint and every table is documented by hand, and hand-written lists rot
quietly: a new route ships, the spec keeps its old shape, and the next reader
trusts the spec. These tests fail when the code grows something the docs do not
mention.

They do not check that the prose is *correct*, only that nothing is missing.
That is the part a machine can do.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import sentinelflow.models  # noqa: F401 - registers the models on the metadata
from sentinelflow.db.session import Base
from sentinelflow.main import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def openapi_paths() -> list[str]:
    return sorted(create_app().openapi()["paths"])


def test_every_endpoint_is_documented(openapi_paths: list[str]) -> None:
    spec = (ROOT / "docs" / "API_SPEC.md").read_text(encoding="utf-8")

    missing = [path for path in openapi_paths if path not in spec]
    assert not missing, (
        "these endpoints exist in the app but are absent from docs/API_SPEC.md: "
        + ", ".join(missing)
    )


def test_every_table_is_documented() -> None:
    model_doc = (ROOT / "docs" / "DATA_MODEL.md").read_text(encoding="utf-8")

    missing = [name for name in sorted(Base.metadata.tables) if name not in model_doc]
    assert not missing, (
        "these tables exist in the models but are absent from docs/DATA_MODEL.md: "
        + ", ".join(missing)
    )


def test_the_ci_workflow_parses_and_calls_real_scripts() -> None:
    """A workflow that references a missing file fails only after a push."""
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    assert set(workflow["jobs"]) >= {"backend", "frontend", "postgres"}

    referenced: list[str] = []
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            for token in (step.get("run") or "").split():
                if token.startswith("scripts/"):
                    referenced.append(token)

    assert referenced, "the workflow should call the shared check script"
    for relative in referenced:
        assert (ROOT / relative).is_file(), f"workflow references missing {relative}"


def test_ci_keeps_the_optional_model_job_out_of_the_required_path() -> None:
    """A required job that needs a secret would block every contributor."""
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )

    optional = workflow["jobs"]["optional-real-model"]
    # Only a manual trigger may reach a job that reads a model key.
    assert optional["if"] == "github.event_name == 'workflow_dispatch'"

    for name, job in workflow["jobs"].items():
        if name == "optional-real-model":
            continue
        serialised = yaml.safe_dump(job)
        assert "secrets." not in serialised, f"required job {name} reads a secret"
