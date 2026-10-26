"""Static checks on the deployment configuration.

Docker is not available in this environment (no daemon, and WSL is blocked by
policy), so the compose stack cannot be started here. These tests do the part
that does not need a daemon: they parse the files and assert the invariants that
make the stack safe to run somewhere that does.

They are not a substitute for `docker compose up`. They catch the mistakes that
are cheap to make and expensive to debug at runtime: a service with no
healthcheck, a dependency that does not wait, a port published on 0.0.0.0, a
secret written as a literal, an image built with `COPY . .` that would bake
`.env` into a layer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose.yaml"
DOCKERFILE = ROOT / "Dockerfile"
FRONTEND_DOCKERFILE = ROOT / "frontend" / "Dockerfile"
NGINX = ROOT / "frontend" / "nginx.conf"
ENV_EXAMPLE = ROOT / ".env.example"

LONG_RUNNING = ("db", "api", "web")


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_defines_the_whole_stack(compose: dict) -> None:
    services = compose["services"]

    assert set(services) == {"db", "migrate", "api", "web"}
    # One image, two roles: the schema is applied by the code that serves it.
    assert services["migrate"]["build"]["context"] == services["api"]["build"]["context"]
    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]


def test_every_long_running_service_has_a_healthcheck(compose: dict) -> None:
    for name in LONG_RUNNING:
        check = compose["services"][name].get("healthcheck")
        assert check, f"{name} has no healthcheck"
        assert check.get("test"), f"{name} healthcheck has no test"
        # A start_period avoids marking a slow first boot as a failure.
        assert check.get("start_period"), f"{name} healthcheck has no start_period"


def test_startup_order_is_enforced_not_hoped_for(compose: dict) -> None:
    services = compose["services"]

    assert services["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    # The API must not start before the schema exists.
    assert (
        services["api"]["depends_on"]["migrate"]["condition"]
        == "service_completed_successfully"
    )
    assert services["api"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_a_failed_migration_does_not_loop(compose: dict) -> None:
    """A restart loop on `migrate` would bury the actual error."""
    assert compose["services"]["migrate"]["restart"] == "no"


def test_database_data_lives_in_a_named_volume(compose: dict) -> None:
    db = compose["services"]["db"]

    assert "sentinelflow_pgdata" in compose["volumes"]
    assert "sentinelflow_pgdata:/var/lib/postgresql/data" in db["volumes"]


def test_nothing_is_published_on_all_interfaces(compose: dict) -> None:
    """No TLS in this stack, so it must not be reachable from the network."""
    for name, service in compose["services"].items():
        for mapping in service.get("ports", []):
            assert str(mapping).startswith("127.0.0.1:"), f"{name} publishes {mapping}"


def test_no_privileged_or_host_network_modes(compose: dict) -> None:
    for name, service in compose["services"].items():
        assert not service.get("privileged"), name
        assert service.get("network_mode") != "host", name


def test_secrets_are_interpolated_never_literal(compose: dict) -> None:
    """A literal secret in compose.yaml would be committed to Git."""
    secretish = re.compile(r"(SECRET|PASSWORD|API_KEY|TOKEN)", re.IGNORECASE)

    for name, service in compose["services"].items():
        for key, value in (service.get("environment") or {}).items():
            if not secretish.search(key):
                continue
            text = str(value)
            assert "${" in text, f"{name}.{key} is a literal secret"
            # `:?` makes compose refuse to start when the value is missing.
            if key in ("JWT_SECRET", "POSTGRES_PASSWORD"):
                assert ":?" in text, f"{name}.{key} must fail fast when unset"


def test_the_api_reaches_the_database_by_service_name(compose: dict) -> None:
    """127.0.0.1 inside a container is the container itself."""
    dsn = compose["services"]["api"]["environment"]["DATABASE_URL"]

    assert "@db:5432/" in dsn
    assert "127.0.0.1" not in dsn
    # Built from the same values the db container was given.
    assert "${POSTGRES_USER" in dsn and "${POSTGRES_PASSWORD" in dsn


def test_migrate_and_api_share_one_environment_block(compose: dict) -> None:
    """If they diverged, the migration could target a different database."""
    assert (
        compose["services"]["migrate"]["environment"]
        == compose["services"]["api"]["environment"]
    )


# --- images -----------------------------------------------------------------


def test_api_image_runs_as_a_non_root_user() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert re.search(r"^USER\s+\w+", text, re.MULTILINE), "no USER directive"
    assert "useradd" in text or "adduser" in text


def test_api_image_does_not_copy_the_whole_tree() -> None:
    """`COPY . .` would bake .env and local databases into a layer."""
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY . ." not in text
    for needed in ("alembic.ini", "migrations"):
        assert needed in text


def test_dockerignore_excludes_local_secrets() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert ".venv" in ignored
    assert "node_modules" in ignored


def test_web_image_is_multi_stage_and_unprivileged() -> None:
    text = FRONTEND_DOCKERFILE.read_text(encoding="utf-8")

    assert text.count("FROM ") >= 2, "expected a build stage and a runtime stage"
    assert "nginx-unprivileged" in text
    assert "npm ci" in text, "the lockfile must be used, not `npm install`"


def test_nginx_proxies_the_api_and_falls_back_to_the_spa() -> None:
    text = NGINX.read_text(encoding="utf-8")

    assert "location /api/" in text
    assert "proxy_pass http://sentinelflow_api" in text
    # Client-side routes like /alerts/<uuid> are not files on disk.
    assert "try_files $uri $uri/ /index.html" in text
    assert "location = /healthz" in text


# --- environment template ---------------------------------------------------


def test_env_example_holds_placeholders_not_secrets() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "CHANGE_ME" in text
    assert "JWT_SECRET=CHANGE_ME" in text
    assert "POSTGRES_PASSWORD=CHANGE_ME" in text
    # An empty LLM_API_KEY is the documented "agent disabled" state.
    assert "LLM_API_KEY=\n" in text or text.rstrip().endswith("LLM_API_KEY=") or "LLM_API_KEY=\n" in text.replace("\r\n", "\n")
    # Nothing that looks like a real credential.
    assert not re.search(r"sk-[A-Za-z0-9]{20,}", text)


def test_env_example_is_the_only_env_file_that_may_be_committed() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert "!.env.example" in ignored
