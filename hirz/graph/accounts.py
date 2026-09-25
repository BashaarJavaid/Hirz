"""The indexed account lookup shared by the pipeline and MCP authentication."""

from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from hirz import db
from hirz.pipeline.models import Principal, Requester, Role


async def resolve_member(
    connection: AsyncConnection, household_id: UUID, principal: Principal
) -> Requester:
    row = (
        await connection.execute(
            sa.select(db.members.c.id, db.members.c.role)
            .join(
                db.member_accounts,
                sa.and_(
                    db.members.c.household_id == db.member_accounts.c.household_id,
                    db.members.c.id == db.member_accounts.c.member_id,
                ),
            )
            .where(
                db.members.c.household_id == household_id,
                db.member_accounts.c.provider == principal.provider,
                db.member_accounts.c.sub == principal.sub,
            )
        )
    ).one_or_none()
    return Requester(
        member_id=str(row.id) if row else None,
        role=cast(Role, row.role) if row else "unknown",
        surface=principal.surface,
    )
