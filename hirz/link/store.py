"""Private local journal: claim once and persist the ending before actuation."""

import asyncio
import fcntl
import json
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric import ec

from hirz.executor.contracts import ending
from hirz.graph.models import utc
from hirz.link.command import Envelope, Rejected, authenticated, fingerprint, verify
from hirz.pipeline.hashing import timestamp
from hirz.pipeline.models import Action, EventType

SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE commands (
  nonce TEXT PRIMARY KEY, action_id TEXT NOT NULL UNIQUE,
  content_hash TEXT NOT NULL, target TEXT NOT NULL, envelope TEXT NOT NULL,
  accepted_at TEXT NOT NULL, ending_due TEXT, ending_done INTEGER NOT NULL DEFAULT 0,
  outcome TEXT
);
CREATE INDEX command_hashes ON commands(content_hash, accepted_at);
CREATE TABLE receipts (
  id TEXT PRIMARY KEY, at TEXT NOT NULL, event_type TEXT NOT NULL,
  payload TEXT NOT NULL
);
"""


def initialize(path: Path, home_id: UUID, key: ec.EllipticCurvePublicKey) -> None:
    """Explicit bootstrap only; an existing or malformed journal is never reset."""
    pin = fingerprint(key)
    if path.parent.is_symlink() or path.parent.stat().st_mode & 0o077:
        raise ValueError("Link journal requires a private directory")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        with connection:
            connection.executemany(
                "INSERT INTO settings VALUES (?, ?)",
                [
                    ("version", "1"),
                    ("home_id", str(home_id)),
                    ("key", pin),
                    ("last_at", ""),
                ],
            )
    finally:
        connection.close()


class Store:
    def __init__(self, path: Path, home_id: UUID, key: ec.EllipticCurvePublicKey):
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as handle:
            info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or path.parent.is_symlink()
                or path.parent.stat().st_mode & 0o077
            ):
                raise ValueError("Link journal must be private and regular")
        # A separate inode avoids conflicting with SQLite's own macOS file locks.
        self.fd = os.open(
            str(path) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("Link process lock must be private and regular")
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.connection = sqlite3.connect(path, timeout=2)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA synchronous=FULL")
            values = dict(self.connection.execute("SELECT key, value FROM settings"))
            if (
                values.get("version") != "1"
                or values.get("home_id") != str(home_id)
                or values.get("key") != fingerprint(key)
                or "last_at" not in values
            ):
                raise ValueError("Link journal home, key or version mismatch")
            self.home_id, self.key = home_id, key
            self.execution_lock = asyncio.Lock()
        except BaseException:
            if hasattr(self, "connection"):
                self.connection.close()
            os.close(self.fd)
            raise

    def close(self) -> None:
        self.connection.close()
        os.close(self.fd)

    @contextmanager
    def write(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def receipt(self, event: EventType, at: datetime, **payload: Any) -> None:
        self.connection.execute(
            "INSERT INTO receipts VALUES (?, ?, ?, ?)",
            (
                str(uuid4()),
                timestamp(at),
                event.value,
                json.dumps(payload, allow_nan=False, sort_keys=True),
            ),
        )

    def reserve(self, value: object, at: datetime) -> Envelope:
        at = utc(at)
        try:
            envelope = verify(value, key=self.key, home_id=self.home_id, at=at)
            command, action = envelope.command, envelope.command.action
            with self.write():
                last_at = self.connection.execute(
                    "SELECT value FROM settings WHERE key='last_at'"
                ).fetchone()[0]
                if last_at and timestamp(at) < last_at:
                    raise Rejected("clock_moved_backwards")
                if self.connection.execute(
                    "SELECT 1 FROM commands WHERE nonce=? OR action_id=? OR "
                    "(content_hash=? AND accepted_at>?)",
                    (
                        str(command.nonce),
                        action.action_id,
                        action.content_hash,
                        timestamp(at - timedelta(hours=24)),
                    ),
                ).fetchone():
                    raise Rejected("already_claimed")
                if self.connection.execute(
                    "SELECT 1 FROM commands WHERE target=? AND ending_due IS NOT NULL "
                    "AND ending_done=0",
                    (action.target.entity,),
                ).fetchone():
                    raise Rejected("ending_pending_for_target")
                due = ending(action, start=at).scheduled_for if action.revert else None
                self.connection.execute(
                    "INSERT INTO commands(nonce,action_id,content_hash,target,envelope,"
                    "accepted_at,ending_due) VALUES (?,?,?,?,?,?,?)",
                    (
                        str(command.nonce),
                        action.action_id,
                        action.content_hash,
                        action.target.entity,
                        envelope.model_dump_json(by_alias=True),
                        timestamp(at),
                        timestamp(due) if due else None,
                    ),
                )
                self.connection.execute(
                    "UPDATE settings SET value=? WHERE key='last_at'", (timestamp(at),)
                )
                self.receipt(
                    EventType.EXECUTION_ATTEMPTED,
                    at,
                    action_id=action.action_id,
                    content_hash=action.content_hash,
                    nonce=str(command.nonce),
                )
            return envelope
        except Rejected as exc:
            with self.write():
                self.receipt(EventType.LINK_REJECTED, at, reason=str(exc))
            raise

    def complete(
        self, action_id: str, at: datetime, *, matched: bool, reverting: bool = False
    ) -> None:
        with self.write():
            if reverting:
                changed = self.connection.execute(
                    "UPDATE commands SET ending_done=? WHERE action_id=? "
                    "AND ending_due IS NOT NULL AND ending_done=0",
                    (int(matched), action_id),
                ).rowcount
            else:
                changed = self.connection.execute(
                    "UPDATE commands SET outcome=? WHERE action_id=? AND outcome IS NULL",
                    ("verified" if matched else "failed", action_id),
                ).rowcount
            if changed != 1:
                raise ValueError("Unknown or already completed Link operation")
            self.receipt(
                EventType.VERIFIED if matched else EventType.VERIFY_FAILED,
                at,
                action_id=action_id,
                ending=reverting,
            )

    def due(self, at: datetime) -> tuple[tuple[Envelope, Action], ...]:
        at = utc(at)
        with self.write():
            last_at = self.connection.execute(
                "SELECT value FROM settings WHERE key='last_at'"
            ).fetchone()[0]
            # An uncertain backwards clock ends bounded operations early, never later.
            rollback = bool(last_at and timestamp(at) < last_at)
            rows = self.connection.execute(
                "SELECT envelope, accepted_at FROM commands WHERE ending_done=0 "
                "AND ending_due IS NOT NULL AND (ending_due<=? OR ?) ORDER BY ending_due",
                (timestamp(at), rollback),
            ).fetchall()
            if not rollback:
                self.connection.execute(
                    "UPDATE settings SET value=? WHERE key='last_at'", (timestamp(at),)
                )
        return tuple(
            (
                envelope := authenticated(json.loads(row["envelope"]), self.key),
                ending(
                    envelope.command.action,
                    start=datetime.fromisoformat(row["accepted_at"]),
                ),
            )
            for row in rows
        )

    def receipts(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(row) | {"payload": json.loads(row["payload"])}
            for row in self.connection.execute("SELECT * FROM receipts ORDER BY rowid")
        )

    def authorized(self, envelope: Envelope, action: Action, at: datetime) -> None:
        """Bind the local transport to a journaled opening or its exact due ending."""
        value = authenticated(envelope.model_dump(by_alias=True), self.key)
        row = self.connection.execute(
            "SELECT * FROM commands WHERE nonce=?", (str(value.command.nonce),)
        ).fetchone()
        if (
            row is None
            or value.command.home_id != self.home_id
            or value != authenticated(json.loads(row["envelope"]), self.key)
        ):
            raise Rejected("unclaimed_command")
        if action == value.command.action and row["outcome"] is None:
            verify(value, key=self.key, home_id=self.home_id, at=at)
            return
        if value.command.action.revert and not row["ending_done"]:
            expected = ending(
                value.command.action, start=datetime.fromisoformat(row["accepted_at"])
            )
            last = self.connection.execute(
                "SELECT value FROM settings WHERE key='last_at'"
            ).fetchone()[0]
            if action == expected and (
                timestamp(at) >= row["ending_due"] or timestamp(at) < last
            ):
                return
        raise Rejected("unclaimed_command")
