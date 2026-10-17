"""Infrastructure secrets are read in memory; invalid values never self-repair."""

import os
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hirz.aws.client import client


def secret(variable: str) -> str:
    result = client("secretsmanager").get_secret_value(SecretId=os.environ[variable])
    value = result.get("SecretString")
    if not isinstance(value, str) or not value:
        raise ValueError("Missing infrastructure secret")
    return value


def database(password: str, *, username: str = "hirz") -> AsyncEngine:
    if os.environ["HIRZ_DATABASE_NAME"] != "hirz_item36":
        raise ValueError("AWS acceptance requires its disposable database")
    return create_async_engine(
        sa.URL.create(
            "postgresql+psycopg",
            username=username,
            password=password,
            host=os.environ["HIRZ_DATABASE_HOST"],
            database="hirz_item36",
        ),
        hide_parameters=True,
        poolclass=sa.pool.NullPool,
        connect_args={
            "connect_timeout": 5,
            "sslmode": "verify-full",
            "sslrootcert": str(Path(__file__).with_name("rds-us-east-1.pem")),
        },
    )
