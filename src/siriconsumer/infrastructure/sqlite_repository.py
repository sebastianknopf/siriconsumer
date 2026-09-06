from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import MqttSinkConfig, SubscriptionCreate, SubscriptionRecord
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionAlreadyExistsError


class SqliteSubscriptionRepository:
    def __init__(self, database_path: str) -> None:
        self._database_path = database_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_ref TEXT PRIMARY KEY,
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
        record.updated_at = datetime.now(timezone.utc)

        try:
            async with aiosqlite.connect(self._database_path) as db:
                await db.execute(
                    """
                    INSERT INTO subscriptions (
                        subscription_ref, config_json, status, last_heartbeat_at, last_message_at,
                        last_service_started_time, created_at, updated_at, last_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._record_values(record),
                )
                await db.commit()
        except aiosqlite.IntegrityError as exc:
            raise SubscriptionAlreadyExistsError(
                f"SubscriptionRef '{config.subscription_ref}' already exists"
            ) from exc

        return record

    async def get(self, subscription_ref: str) -> SubscriptionRecord | None:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM subscriptions WHERE subscription_ref = ?",
                (subscription_ref,),
            )
            row = await cursor.fetchone()

        return self._to_record(row) if row else None

    async def list_all(self) -> list[SubscriptionRecord]:
        return await self._query("SELECT * FROM subscriptions ORDER BY created_at")

    async def list_recoverable(self) -> list[SubscriptionRecord]:
        return await self._query(
            "SELECT * FROM subscriptions WHERE status != ? ORDER BY created_at",
            (SubscriptionStatus.TERMINATED.value,),
        )

    async def list_by_provider(self, provider_url: str) -> list[SubscriptionRecord]:
        records = await self.list_all()
        return [record for record in records if str(record.config.provider_url) == provider_url]

    async def save(self, record: SubscriptionRecord) -> None:
        record.updated_at = datetime.now(timezone.utc)
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                """
                UPDATE subscriptions SET
                    config_json = ?,
                    status = ?,
                    last_heartbeat_at = ?,
                    last_message_at = ?,
                    last_service_started_time = ?,
                    updated_at = ?,
                    last_error = ?
                WHERE subscription_ref = ?
                """,
                (
                    self._serialize_config(record.config),
                    record.status.value,
                    self._dt(record.last_heartbeat_at),
                    self._dt(record.last_message_at),
                    self._dt(record.last_service_started_time),
                    self._dt(record.updated_at),
                    record.last_error,
                    record.config.subscription_ref,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(record.config.subscription_ref)

            await db.commit()

    @staticmethod
    def _serialize_config(config: SubscriptionCreate) -> str:
        """Serialize subscription configuration for durable storage.

        Pydantic intentionally masks SecretStr values during JSON serialization.
        Durable storage must retain the actual MQTT password so the subscription
        can be reconstructed after a restart. Only this persistence path unwraps
        the secret; normal API/log serialization remains masked.
        """
        data = config.model_dump(mode="json")
        if isinstance(config.sink, MqttSinkConfig) and config.sink.password is not None:
            sink = data.get("sink")
            if isinstance(sink, dict):
                sink["password"] = config.sink.password.get_secret_value()

        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    async def update_status(
        self, subscription_ref: str, status: SubscriptionStatus, error: str | None = None
    ) -> None:
        record = await self.get(subscription_ref)
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

    def _record_values(self, record: SubscriptionRecord) -> tuple[object, ...]:
        return (
            record.config.subscription_ref,
            self._serialize_config(record.config),
            record.status.value,
            self._dt(record.last_heartbeat_at),
            self._dt(record.last_message_at),
            self._dt(record.last_service_started_time),
            self._dt(record.created_at),
            self._dt(record.updated_at),
            record.last_error,
        )

    @staticmethod
    def _dt(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    def _to_record(self, row: aiosqlite.Row) -> SubscriptionRecord:
        config = SubscriptionCreate.model_validate_json(row["config_json"])
        if config.subscription_ref != row["subscription_ref"]:
            raise ValueError(
                "Stored subscription_ref does not match the subscription_ref in config_json"
            )

        return SubscriptionRecord(
            config=config,
            status=SubscriptionStatus(row["status"]),
            last_heartbeat_at=self._parse_dt(row["last_heartbeat_at"]),
            last_message_at=self._parse_dt(row["last_message_at"]),
            last_service_started_time=self._parse_dt(row["last_service_started_time"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_error=row["last_error"],
        )
