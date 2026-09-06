from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import aiosqlite

from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord


class SqliteSubscriptionRepository:
    def __init__(self, database_path: str) -> None:
        self._database_path = database_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY,
                    config_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_heartbeat_at TEXT,
                    last_message_at TEXT,
                    last_service_started_time TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT
                )
                """
            )

            await db.commit()

    async def create(self, config: SubscriptionCreate) -> SubscriptionRecord:
        record = SubscriptionRecord(config=config)
        await self.save(record)

        return record

    async def get(self, subscription_id: UUID) -> SubscriptionRecord | None:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM subscriptions WHERE id = ?", (str(subscription_id),))
            row = await cursor.fetchone()

        return self._to_record(row) if row else None

    async def get_by_ref(self, subscription_ref: str) -> SubscriptionRecord | None:
        records = await self.list_all()
        for record in records:
            if record.config.subscription_ref == subscription_ref:
                return record

        return None

    async def list_all(self) -> list[SubscriptionRecord]:
        return await self._query("SELECT * FROM subscriptions ORDER BY created_at")

    async def list_recoverable(self) -> list[SubscriptionRecord]:
        return await self._query(
            "SELECT * FROM subscriptions WHERE status != ? ORDER BY created_at",
            (SubscriptionStatus.TERMINATED.value,),
        )

    async def list_by_provider(self, provider_url: str) -> list[SubscriptionRecord]:
        records = await self.list_all()
        return [r for r in records if str(r.config.provider_url) == provider_url]

    async def save(self, record: SubscriptionRecord) -> None:
        record.updated_at = datetime.now(timezone.utc)
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                INSERT INTO subscriptions (
                    id, config_json, status, last_heartbeat_at, last_message_at,
                    last_service_started_time, created_at, updated_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    config_json=excluded.config_json,
                    status=excluded.status,
                    last_heartbeat_at=excluded.last_heartbeat_at,
                    last_message_at=excluded.last_message_at,
                    last_service_started_time=excluded.last_service_started_time,
                    updated_at=excluded.updated_at,
                    last_error=excluded.last_error
                """,
                (
                    str(record.id),
                    record.config.model_dump_json(),
                    record.status.value,
                    self._dt(record.last_heartbeat_at),
                    self._dt(record.last_message_at),
                    self._dt(record.last_service_started_time),
                    self._dt(record.created_at),
                    self._dt(record.updated_at),
                    record.last_error,
                ),
            )

            await db.commit()

    async def update_status(
        self, subscription_id: UUID, status: SubscriptionStatus, error: str | None = None
    ) -> None:
        record = await self.get(subscription_id)
        if record is None:
            return

        record.status = status
        record.last_error = error

        await self.save(record)

    async def _query(self, sql: str, params: tuple[object, ...] = ()) -> list[SubscriptionRecord]:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()

        return [self._to_record(row) for row in rows]

    @staticmethod
    def _dt(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    def _to_record(self, row: aiosqlite.Row) -> SubscriptionRecord:
        return SubscriptionRecord(
            id=UUID(row["id"]),
            config=SubscriptionCreate.model_validate_json(row["config_json"]),
            status=SubscriptionStatus(row["status"]),
            last_heartbeat_at=self._parse_dt(row["last_heartbeat_at"]),
            last_message_at=self._parse_dt(row["last_message_at"]),
            last_service_started_time=self._parse_dt(row["last_service_started_time"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_error=row["last_error"],
        )
