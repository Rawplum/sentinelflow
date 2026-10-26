"""Plumbing for the performance runs: a real server, a clean database, a timer.

The numbers only mean something if the thing being measured is the thing that
runs in production. So the harness starts a real uvicorn process over loopback
HTTP instead of calling the app in-process: an in-process client would share the
interpreter with the server, and the GIL would show up as fake latency.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Kept short: these are loopback requests to a local process.
HTTP_TIMEOUT = 120


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def database_url(name: str) -> str:
    """Build a DSN for a perf database from the environment.

    PERF_DATABASE_BASE is the server part, e.g.
    ``postgresql+psycopg://postgres@127.0.0.1:55432``. Defaults to the local
    development server so a run needs no configuration on this machine.
    """
    base = os.environ.get(
        "PERF_DATABASE_BASE", "postgresql+psycopg://postgres@127.0.0.1:55432"
    )
    return f"{base}/{name}"


def reset_database(name: str) -> str:
    """Drop and recreate the perf database, then apply migrations."""
    url = database_url(name)
    admin = create_engine(database_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()

    env = dict(os.environ, DATABASE_URL=url, JWT_SECRET="perf-only-secret-" + "x" * 32)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic failed:\n{result.stdout}\n{result.stderr}")
    return url


def session_factory_for(url: str):
    engine = create_engine(url)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@dataclass
class Server:
    """A real uvicorn process serving the API under test."""

    url: str
    port: int
    process: subprocess.Popen
    env: dict[str, str] = field(default_factory=dict)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=15)


@contextmanager
def running_server(url: str, *, extra_env: dict[str, str] | None = None):
    port = free_port()
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": url,
            "JWT_SECRET": "perf-only-secret-" + "x" * 32,
            "APP_ENV": "performance",
            "AGENT_WORKER_ENABLED": "true",
            # Keep the log level quiet: request logging would dominate the
            # measurement at these volumes.
            "LOG_LEVEL": "warning",
        }
    )
    if extra_env:
        env.update(extra_env)

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "sentinelflow.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    server = Server(url=url, port=port, process=process, env=env)
    try:
        _wait_until_ready(server)
        yield server
    finally:
        server.stop()


def _wait_until_ready(server: Server, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        if server.process.poll() is not None:
            stderr = server.process.stderr.read().decode("utf-8", "replace")[-2000:]
            raise RuntimeError(f"server exited early:\n{stderr}")
        try:
            with urllib.request.urlopen(
                f"{server.base}/health/ready", timeout=3
            ) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"server not ready after {timeout}s: {last}")


class Client:
    """Minimal keep-alive HTTP client so connection setup is not measured."""

    def __init__(self, base_url: str) -> None:
        self._host = base_url.replace("http://", "")
        self._connection: http.client.HTTPConnection | None = None
        self.token: str | None = None

    def _conn(self) -> http.client.HTTPConnection:
        if self._connection is None:
            self._connection = http.client.HTTPConnection(
                self._host, timeout=HTTP_TIMEOUT
            )
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        auth: bool = True,
    ) -> tuple[int, bytes, float]:
        headers = {"Accept": "application/json"}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            headers["Content-Length"] = str(len(payload))

        started = time.perf_counter()
        connection = self._conn()
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            data = response.read()
        except (http.client.HTTPException, OSError):
            # A dropped keep-alive connection is normal; retry once on a new one.
            self.close()
            connection = self._conn()
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            data = response.read()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return response.status, data, elapsed_ms

    def login(self, username: str, password: str) -> None:
        status, data, _ = self.request(
            "POST",
            "/api/v1/auth/login",
            {"username": username, "password": password},
            auth=False,
        )
        if status != 200:
            raise RuntimeError(f"login failed: {status} {data[:200]}")
        self.token = json.loads(data)["access_token"]


@dataclass
class Sample:
    """One scenario's measurements."""

    name: str
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0
    payload_bytes: int = 0

    def add(self, elapsed_ms: float, status: int, size: int) -> None:
        self.latencies_ms.append(elapsed_ms)
        if status >= 400:
            self.errors += 1
        self.payload_bytes = max(self.payload_bytes, size)

    @property
    def count(self) -> int:
        return len(self.latencies_ms)

    @property
    def error_rate(self) -> float:
        return self.errors / self.count if self.count else 0.0

    def percentile(self, p: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        # Nearest-rank: the smallest value that covers p of the samples.
        index = max(0, min(len(ordered) - 1, round(p * len(ordered) + 0.5) - 1))
        return ordered[index]

    @property
    def p50(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p95(self) -> float:
        return self.percentile(0.95)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.latencies_ms) if self.latencies_ms else 0.0


def timed(sample: Sample, client: Client, method: str, path: str, body=None) -> bytes:
    status, data, elapsed = client.request(method, path, body)
    sample.add(elapsed, status, len(data))
    return data


__all__ = [
    "Client",
    "Sample",
    "Server",
    "database_url",
    "free_port",
    "reset_database",
    "running_server",
    "session_factory_for",
    "timed",
]
