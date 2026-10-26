import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_alembic_upgrade_and_downgrade() -> None:
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MIGRATION_TEST_DATABASE_URL is not set")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("The migration test requires PostgreSQL")
    if "test" not in url.lower():
        pytest.fail("MIGRATION_TEST_DATABASE_URL must point to a test database")

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DROP TABLE IF EXISTS investigation_rounds, "
                    "investigation_tool_calls, "
                    "investigations, investigation_reports, "
                    "alert_status_history, revoked_tokens, login_attempts, "
                    "audit_logs, users, alert_events, alerts, security_events "
                    "CASCADE"
                )
            )
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))

        command.upgrade(config, "head")

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "security_events",
            "alerts",
            "alert_events",
            "users",
            "audit_logs",
            "investigation_reports",
            "alert_status_history",
            "revoked_tokens",
            "login_attempts",
            "investigations",
            "investigation_tool_calls",
            "investigation_rounds",
        } <= tables

        check_names = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("security_events")
        }
        assert "ck_security_events_outcome" in check_names
        assert "ck_security_events_raw_message_length" in check_names

        unique_names = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("alerts")
        }
        assert "uq_alerts_dedup_key" in unique_names

        index_names = {
            index["name"] for index in inspector.get_indexes("security_events")
        }
        assert "ix_security_events_occurred_at" in index_names
        assert "ix_security_events_user_ip_occurred_at" in index_names

        foreign_tables = {
            fk["referred_table"] for fk in inspector.get_foreign_keys("alert_events")
        }
        assert foreign_tables == {"alerts", "security_events"}

        user_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("users")
        }
        assert {
            "ck_users_role",
            "ck_users_username_lower",
            "ck_users_username_length",
        } <= user_checks

        user_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("users")
        }
        assert "uq_users_username" in user_uniques

        audit_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("audit_logs")
        }
        assert "ck_audit_logs_outcome" in audit_checks

        audit_foreign_tables = {
            fk["referred_table"] for fk in inspector.get_foreign_keys("audit_logs")
        }
        assert audit_foreign_tables == {"users"}

        audit_indexes = {index["name"] for index in inspector.get_indexes("audit_logs")}
        assert {
            "ix_audit_logs_actor_created_at",
            "ix_audit_logs_action_created_at",
            "ix_audit_logs_created_at",
        } <= audit_indexes

        report_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("investigation_reports")
        }
        assert {
            "ck_investigation_reports_status",
            "ck_investigation_reports_generator",
            "ck_investigation_reports_version",
            "ck_investigation_reports_finalized_at",
        } <= report_checks

        report_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("investigation_reports")
        }
        assert "uq_investigation_reports_alert_version" in report_uniques

        report_foreign_tables = {
            fk["referred_table"]
            for fk in inspector.get_foreign_keys("investigation_reports")
        }
        assert report_foreign_tables == {"alerts", "users"}

        history_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("alert_status_history")
        }
        assert {
            "ck_alert_status_history_to_status",
            "ck_alert_status_history_from_status",
        } <= history_checks

        revoked_indexes = {
            index["name"] for index in inspector.get_indexes("revoked_tokens")
        }
        assert "ix_revoked_tokens_expires_at" in revoked_indexes

        attempt_indexes = {
            index["name"] for index in inspector.get_indexes("login_attempts")
        }
        assert "ix_login_attempts_subject_attempted" in attempt_indexes

        investigation_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("investigations")
        }
        assert "ck_investigations_status" in investigation_checks

        investigation_fks = {
            fk["referred_table"] for fk in inspector.get_foreign_keys("investigations")
        }
        assert investigation_fks == {"alerts", "investigation_reports", "users"}

        tool_call_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "investigation_tool_calls"
            )
        }
        assert "ck_investigation_tool_calls_status" in tool_call_checks

        round_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("investigation_rounds")
        }
        assert {
            "ck_investigation_rounds_outcome",
            "ck_investigation_rounds_index",
        } <= round_checks

        round_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("investigation_rounds")
        }
        assert "uq_investigation_rounds_attempt_index" in round_uniques

        round_columns = {
            column["name"] for column in inspector.get_columns("investigation_rounds")
        }
        assert "attempt_index" in round_columns
        tool_call_columns = {
            column["name"]
            for column in inspector.get_columns("investigation_tool_calls")
        }
        assert "attempt_index" in tool_call_columns

        investigation_columns = {
            column["name"] for column in inspector.get_columns("investigations")
        }
        assert {
            "request_id",
            "duration_ms",
            "attempt_count",
            "max_attempts",
            "lease_expires_at",
            "next_attempt_at",
            "started_at",
            "error_code",
        } <= investigation_columns

        queue_indexes = {
            index["name"] for index in inspector.get_indexes("investigations")
        }
        assert "ix_investigations_queue" in queue_indexes

        status_sql = next(
            (
                check["sqltext"]
                for check in inspector.get_check_constraints("investigations")
                if check["name"] == "ck_investigations_status"
            ),
            "",
        )
        assert "pending" in status_sql

        # 0006 must be reversible on its own without touching 0005 tables.
        command.downgrade(config, "0005")
        inspector = inspect(engine)
        columns_after_0006 = {
            column["name"] for column in inspector.get_columns("investigations")
        }
        assert "attempt_count" not in columns_after_0006
        assert "error_code" not in columns_after_0006
        round_uniques_after = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("investigation_rounds")
        }
        assert "uq_investigation_rounds_index" in round_uniques_after
        command.upgrade(config, "head")

        # 0005 must be reversible on its own without touching 0004 tables.
        command.downgrade(config, "0004")
        inspector = inspect(engine)
        remaining_after_0005 = set(inspector.get_table_names())
        assert "investigation_rounds" not in remaining_after_0005
        assert {"investigations", "investigation_tool_calls"} <= remaining_after_0005
        columns_after_0005 = {
            column["name"] for column in inspector.get_columns("investigations")
        }
        assert "request_id" not in columns_after_0005
        assert "duration_ms" not in columns_after_0005

        # 0004 must be reversible on its own without touching 0003 tables.
        command.downgrade(config, "0003")
        inspector = inspect(engine)
        remaining_after_0004 = set(inspector.get_table_names())
        assert "investigations" not in remaining_after_0004
        assert "investigation_tool_calls" not in remaining_after_0004
        assert {
            "investigation_reports",
            "alert_status_history",
            "revoked_tokens",
            "login_attempts",
        } <= remaining_after_0004

        # 0003 must be reversible on its own without touching 0001/0002 tables.
        command.downgrade(config, "0002")
        inspector = inspect(engine)
        remaining_after_0003 = set(inspector.get_table_names())
        assert "investigation_reports" not in remaining_after_0003
        assert "alert_status_history" not in remaining_after_0003
        assert "revoked_tokens" not in remaining_after_0003
        assert "login_attempts" not in remaining_after_0003
        assert {"alerts", "security_events", "users", "audit_logs"} <= (
            remaining_after_0003
        )

        command.downgrade(config, "base")

        inspector = inspect(engine)
        remaining = set(inspector.get_table_names())
        assert not (
            {
                "security_events",
                "alerts",
                "alert_events",
                "users",
                "audit_logs",
                "investigation_reports",
                "alert_status_history",
                "revoked_tokens",
                "login_attempts",
                "investigations",
                "investigation_tool_calls",
                "investigation_rounds",
            }
            & remaining
        )
    finally:
        engine.dispose()
