"""Explicit one-off initialization. Never invoked by application startup."""

import argparse
import asyncio
import json
import os
import secrets

import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from alembic import command
from hirz import db
from hirz.aws.client import call, client
from hirz.aws.config import database, secret
from hirz.aws.fixture import load, policy_seeds
from hirz.graph.models import now
from hirz.graph.seeds import load_seeds
from hirz.local import signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.twin.execution import bootstrap


async def initialize() -> None:
    master = json.loads(secret("HIRZ_MASTER_SECRET"))
    password = secret("HIRZ_DATABASE_SECRET")
    engine = database(master["password"], username=master["username"])
    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text("SELECT pg_advisory_xact_lock(360035)"))
            exists = await connection.scalar(
                sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'hirz'")
            )
            if not exists:
                # Password is generated alphanumeric by CDK; never interpolate arbitrary SQL.
                if (
                    not password.isascii()
                    or not password.isalnum()
                    or len(password) != 40
                ):
                    raise ValueError("Unexpected generated database password format")
                await connection.execute(
                    sa.text(
                        "CREATE ROLE hirz LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '"
                        + password
                        + "'"
                    )
                )
            # PostgreSQL 16 requires SET membership to transfer ownership; RDS master is not SUPERUSER.
            # https://www.postgresql.org/docs/16/sql-alterdatabase.html
            await connection.execute(
                sa.text("GRANT hirz TO CURRENT_USER WITH INHERIT TRUE, SET TRUE")
            )
            await connection.execute(
                sa.text("ALTER DATABASE hirz_item36 OWNER TO hirz")
            )
            await connection.execute(sa.text("ALTER SCHEMA public OWNER TO hirz"))
            await connection.execute(
                sa.text("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            )
    finally:
        await engine.dispose()
    engine = database(password)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(db.require_empty_audit)
            await connection.rollback()
            sdk = client("secretsmanager")
            audit = secret("HIRZ_AUDIT_SECRET")
            if audit == "UNINITIALIZED":
                audit = (
                    ec.generate_private_key(ec.SECP256R1())
                    .private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                    .decode()
                )
                await call(
                    sdk,
                    "put_secret_value",
                    SecretId=os.environ["HIRZ_AUDIT_SECRET"],
                    SecretString=audit,
                )
            signing_key({"AUDIT_SIGNING_KEY": audit})
            tick = secret("HIRZ_TICK_SECRET")
            if tick == "UNINITIALIZED":
                await call(
                    sdk,
                    "put_secret_value",
                    SecretId=os.environ["HIRZ_TICK_SECRET"],
                    SecretString=secrets.token_hex(32),
                )
            elif len(tick) != 64 or any(c not in "0123456789abcdef" for c in tick):
                raise ValueError("Malformed tick secret; restore it explicitly")
            machine = await call(
                client("cognito-idp"),
                "describe_user_pool_client",
                UserPoolId=os.environ["HIRZ_USER_POOL"],
                ClientId=os.environ["HIRZ_MACHINE_CLIENT"],
            )
            credential = machine["UserPoolClient"]["ClientSecret"]
            if not isinstance(credential, str) or not credential:
                raise ValueError("Cognito machine client has no secret")
            stored = secret("HIRZ_MACHINE_SECRET")
            if stored == "UNINITIALIZED":
                await call(
                    sdk,
                    "put_secret_value",
                    SecretId=os.environ["HIRZ_MACHINE_SECRET"],
                    SecretString=credential,
                )
            elif not secrets.compare_digest(stored, credential):
                raise ValueError(
                    "Cognito machine secret differs; restore it explicitly"
                )
    finally:
        await engine.dispose()


async def migrate() -> None:
    engine = database(secret("HIRZ_DATABASE_SECRET"))
    try:
        async with engine.begin() as connection:

            def upgrade(sync: sa.Connection) -> None:
                config = db.migration_config()
                config.attributes["connection"] = sync
                command.upgrade(config, "head")

            await connection.run_sync(upgrade)
    finally:
        await engine.dispose()


async def seed() -> None:
    engine = database(secret("HIRZ_DATABASE_SECRET"))
    try:
        async with engine.connect() as connection:
            await connection.run_sync(db.require_current)
            present = await connection.scalar(
                sa.select(sa.exists().select_from(db.households))
            )
            await connection.rollback()
            if present:
                raise ValueError("Fixture already exists; bootstrap never rewrites it")
            await bootstrap(
                load(),
                connection,
                audit=AuditWriter(
                    signing_key({"AUDIT_SIGNING_KEY": secret("HIRZ_AUDIT_SECRET")})
                ),
            )
            await load_seeds(connection, policy_seeds(), now)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["initialize", "migrate", "seed"])
    args = parser.parse_args()
    asyncio.run(
        {"initialize": initialize, "migrate": migrate, "seed": seed}[args.operation]()
    )
    print(json.dumps({"operation": args.operation, "status": "passed"}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "type": type(exc).__name__}))
        raise SystemExit(1) from None
