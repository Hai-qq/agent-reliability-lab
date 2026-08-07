"""Deterministic, SQLite-backed synthetic Travel environment."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any, Literal

from arl.core.types import (
    Observation,
    SnapshotRef,
    StepResult,
    ToolAction,
    canonical_json,
    digest_value,
)

BOOK_TASK_ID = "travel.book_policy_compliant_itinerary"
RECOVERY_TASK_ID = "travel.recover_bundle_after_flight_failure"
TASK_IDS = (BOOK_TASK_ID, RECOVERY_TASK_ID)
ENV_VERSION = "travel-v0.6.0"
SCHEMA_VERSION = "1.0"

FaultMode = Literal[
    "none",
    "flight_postcommit_timeout_once",
    "preferred_flight_unavailable",
]

_WRITE_TOOLS = {
    "flights.book",
    "hotels.book",
    "hotels.cancel",
    "travel.resolve_booking_request",
}
_READ_TOOLS = {"flights.get_booking", "hotels.get_reservation"}

_TABLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "flights",
        "flight_id",
        (
            "flight_id",
            "origin",
            "destination",
            "depart_at",
            "arrive_at",
            "price_cents",
            "refundable",
            "available_seats",
        ),
    ),
    (
        "hotels",
        "hotel_id",
        (
            "hotel_id",
            "city",
            "check_in",
            "check_out",
            "price_cents",
            "refundable",
            "available_rooms",
        ),
    ),
    (
        "payment_methods",
        "payment_id",
        ("payment_id", "user_id", "active"),
    ),
    (
        "booking_requests",
        "request_id",
        (
            "request_id",
            "user_id",
            "origin",
            "destination",
            "budget_cents",
            "status",
            "selected_flight_booking_id",
            "selected_hotel_reservation_id",
        ),
    ),
    (
        "flight_bookings",
        "booking_id",
        (
            "booking_id",
            "flight_id",
            "user_id",
            "payment_id",
            "status",
            "price_cents",
            "confirmed_nonrefundable",
        ),
    ),
    (
        "hotel_reservations",
        "reservation_id",
        (
            "reservation_id",
            "hotel_id",
            "user_id",
            "payment_id",
            "status",
            "price_cents",
            "confirmed_nonrefundable",
        ),
    ),
    ("travel_metadata", "key", ("key", "value")),
    (
        "idempotency_records",
        "idempotency_key",
        (
            "idempotency_key",
            "tool_name",
            "request_digest",
            "result_json",
            "committed_state_version",
        ),
    ),
)


@dataclass(frozen=True)
class FlightOption:
    flight_id: str
    origin: str
    destination: str
    depart_at: str
    arrive_at: str
    price_cents: int
    refundable: bool
    available_seats: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FlightOption:
        return cls(**value)


@dataclass(frozen=True)
class HotelOption:
    hotel_id: str
    city: str
    check_in: str
    check_out: str
    price_cents: int
    refundable: bool
    available_rooms: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> HotelOption:
        return cls(**value)


@dataclass(frozen=True)
class BookTaskSpec:
    task_id: str
    seed: int
    user_id: str
    request_id: str
    payment_id: str
    flight_booking_id: str
    hotel_reservation_id: str
    origin: str
    destination: str
    budget_cents: int
    require_refundable: bool
    flights: tuple[FlightOption, ...]
    hotels: tuple[HotelOption, ...]
    target_flight_id: str
    target_hotel_id: str
    expected_total_cents: int

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["flights"] = [flight.as_dict() for flight in self.flights]
        value["hotels"] = [hotel.as_dict() for hotel in self.hotels]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BookTaskSpec:
        return cls(
            **{key: item for key, item in value.items() if key not in {"flights", "hotels"}},
            flights=tuple(FlightOption.from_dict(item) for item in value["flights"]),
            hotels=tuple(HotelOption.from_dict(item) for item in value["hotels"]),
        )


@dataclass(frozen=True)
class RecoveryTaskSpec:
    task_id: str
    seed: int
    user_id: str
    request_id: str
    payment_id: str
    origin: str
    destination: str
    budget_cents: int
    preferred_flight: FlightOption
    preferred_hotel: HotelOption
    backup_flight: FlightOption
    backup_hotel: HotelOption
    preferred_flight_booking_id: str
    preferred_hotel_reservation_id: str
    backup_flight_booking_id: str
    backup_hotel_reservation_id: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("preferred_flight", "preferred_hotel", "backup_flight", "backup_hotel"):
            value[key] = getattr(self, key).as_dict()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RecoveryTaskSpec:
        option_keys = {
            "preferred_flight": FlightOption,
            "preferred_hotel": HotelOption,
            "backup_flight": FlightOption,
            "backup_hotel": HotelOption,
        }
        scalars = {key: item for key, item in value.items() if key not in option_keys}
        options = {key: factory.from_dict(value[key]) for key, factory in option_keys.items()}
        return cls(**scalars, **options)


TravelTaskSpec = BookTaskSpec | RecoveryTaskSpec


def book_task_for_seed(seed: int) -> BookTaskSpec:
    if seed < 0:
        raise ValueError("seed must be non-negative")
    day = 10 + seed
    origin = "SYN"
    destination = "TST"
    flights = (
        FlightOption(
            flight_id=f"synthetic-flight-{seed}-refundable",
            origin=origin,
            destination=destination,
            depart_at=f"2026-10-{day:02d}T08:00:00Z",
            arrive_at=f"2026-10-{day:02d}T10:00:00Z",
            price_cents=31_000 + seed * 500,
            refundable=True,
            available_seats=3 + seed,
        ),
        FlightOption(
            flight_id=f"synthetic-flight-{seed}-final-sale",
            origin=origin,
            destination=destination,
            depart_at=f"2026-10-{day:02d}T09:00:00Z",
            arrive_at=f"2026-10-{day:02d}T11:00:00Z",
            price_cents=24_000 + seed * 400,
            refundable=False,
            available_seats=4 + seed,
        ),
    )
    hotels = (
        HotelOption(
            hotel_id=f"synthetic-hotel-{seed}-a",
            city=destination,
            check_in=f"2026-10-{day:02d}T15:00:00Z",
            check_out=f"2026-10-{day + 1:02d}T11:00:00Z",
            price_cents=18_000 + seed * 300,
            refundable=True,
            available_rooms=4 + seed,
        ),
        HotelOption(
            hotel_id=f"synthetic-hotel-{seed}-b",
            city=destination,
            check_in=f"2026-10-{day:02d}T14:00:00Z",
            check_out=f"2026-10-{day + 1:02d}T11:00:00Z",
            price_cents=16_500 + seed * 250,
            refundable=True,
            available_rooms=5 + seed,
        ),
    )
    combinations = [
        (flight, hotel)
        for flight in flights
        for hotel in hotels
        if flight.refundable
        and hotel.refundable
        and flight.destination == hotel.city
        and flight.arrive_at <= hotel.check_in
    ]
    target_flight, target_hotel = min(
        combinations,
        key=lambda pair: (
            pair[0].price_cents + pair[1].price_cents,
            pair[0].flight_id,
            pair[1].hotel_id,
        ),
    )
    expected_total = target_flight.price_cents + target_hotel.price_cents
    return BookTaskSpec(
        task_id=BOOK_TASK_ID,
        seed=seed,
        user_id=f"synthetic-traveler-{seed}",
        request_id=f"synthetic-travel-request-{seed}",
        payment_id=f"synthetic-payment-{seed}",
        flight_booking_id=f"synthetic-flight-booking-{seed}",
        hotel_reservation_id=f"synthetic-hotel-reservation-{seed}",
        origin=origin,
        destination=destination,
        budget_cents=55_000 + seed * 1_000,
        require_refundable=True,
        flights=flights,
        hotels=hotels,
        target_flight_id=target_flight.flight_id,
        target_hotel_id=target_hotel.hotel_id,
        expected_total_cents=expected_total,
    )


def recovery_task_for_seed(seed: int) -> RecoveryTaskSpec:
    if seed < 0:
        raise ValueError("seed must be non-negative")
    day = 20 + seed
    origin = "SYN"
    destination = "TST"
    return RecoveryTaskSpec(
        task_id=RECOVERY_TASK_ID,
        seed=seed,
        user_id=f"synthetic-traveler-{seed}",
        request_id=f"synthetic-recovery-request-{seed}",
        payment_id=f"synthetic-payment-{seed}",
        origin=origin,
        destination=destination,
        budget_cents=55_000 + seed * 1_000,
        preferred_flight=FlightOption(
            flight_id=f"synthetic-preferred-flight-{seed}",
            origin=origin,
            destination=destination,
            depart_at=f"2026-10-{day:02d}T08:00:00Z",
            arrive_at=f"2026-10-{day:02d}T10:00:00Z",
            price_cents=30_000 + seed * 400,
            refundable=True,
            available_seats=2 + seed,
        ),
        preferred_hotel=HotelOption(
            hotel_id=f"synthetic-preferred-hotel-{seed}",
            city=destination,
            check_in=f"2026-10-{day:02d}T15:00:00Z",
            check_out=f"2026-10-{day + 1:02d}T11:00:00Z",
            price_cents=15_000 + seed * 250,
            refundable=True,
            available_rooms=3 + seed,
        ),
        backup_flight=FlightOption(
            flight_id=f"synthetic-backup-flight-{seed}",
            origin=origin,
            destination=destination,
            depart_at=f"2026-10-{day:02d}T11:00:00Z",
            arrive_at=f"2026-10-{day:02d}T13:00:00Z",
            price_cents=34_000 + seed * 400,
            refundable=True,
            available_seats=3 + seed,
        ),
        backup_hotel=HotelOption(
            hotel_id=f"synthetic-backup-hotel-{seed}",
            city=destination,
            check_in=f"2026-10-{day:02d}T16:00:00Z",
            check_out=f"2026-10-{day + 1:02d}T11:00:00Z",
            price_cents=16_000 + seed * 250,
            refundable=True,
            available_rooms=4 + seed,
        ),
        preferred_flight_booking_id=f"synthetic-preferred-flight-booking-{seed}",
        preferred_hotel_reservation_id=f"synthetic-preferred-hotel-reservation-{seed}",
        backup_flight_booking_id=f"synthetic-backup-flight-booking-{seed}",
        backup_hotel_reservation_id=f"synthetic-backup-hotel-reservation-{seed}",
    )


class TravelEnvironment:
    """Resettable synthetic travel world with idempotent booking operations."""

    def __init__(self, fault_mode: FaultMode = "none") -> None:
        if fault_mode not in {
            "none",
            "flight_postcommit_timeout_once",
            "preferred_flight_unavailable",
        }:
            raise ValueError(f"Unknown fault mode: {fault_mode}")
        self.fault_mode = fault_mode
        self.last_fault_id: str | None = None
        self._connection = sqlite3.connect(":memory:", isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        self._task: TravelTaskSpec | None = None
        self._state_version = 0
        self._logical_time = 0
        self._fault_attempts: dict[str, int] = {}

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE flights (
                flight_id TEXT PRIMARY KEY,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                depart_at TEXT NOT NULL,
                arrive_at TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                refundable INTEGER NOT NULL CHECK(refundable IN (0, 1)),
                available_seats INTEGER NOT NULL CHECK(available_seats >= 0)
            );
            CREATE TABLE hotels (
                hotel_id TEXT PRIMARY KEY,
                city TEXT NOT NULL,
                check_in TEXT NOT NULL,
                check_out TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                refundable INTEGER NOT NULL CHECK(refundable IN (0, 1)),
                available_rooms INTEGER NOT NULL CHECK(available_rooms >= 0)
            );
            CREATE TABLE payment_methods (
                payment_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                active INTEGER NOT NULL CHECK(active IN (0, 1))
            );
            CREATE TABLE booking_requests (
                request_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                budget_cents INTEGER NOT NULL CHECK(budget_cents >= 0),
                status TEXT NOT NULL,
                selected_flight_booking_id TEXT,
                selected_hotel_reservation_id TEXT
            );
            CREATE TABLE flight_bookings (
                booking_id TEXT PRIMARY KEY,
                flight_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                payment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                confirmed_nonrefundable INTEGER NOT NULL CHECK(confirmed_nonrefundable IN (0, 1)),
                FOREIGN KEY (flight_id) REFERENCES flights(flight_id),
                FOREIGN KEY (payment_id) REFERENCES payment_methods(payment_id)
            );
            CREATE TABLE hotel_reservations (
                reservation_id TEXT PRIMARY KEY,
                hotel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                payment_id TEXT NOT NULL,
                status TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                confirmed_nonrefundable INTEGER NOT NULL CHECK(confirmed_nonrefundable IN (0, 1)),
                FOREIGN KEY (hotel_id) REFERENCES hotels(hotel_id),
                FOREIGN KEY (payment_id) REFERENCES payment_methods(payment_id)
            );
            CREATE TABLE travel_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE idempotency_records (
                idempotency_key TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                result_json TEXT NOT NULL,
                committed_state_version INTEGER NOT NULL
            );
            """
        )

    @property
    def task(self) -> TravelTaskSpec:
        if self._task is None:
            raise RuntimeError("Environment must be reset before use")
        return self._task

    @property
    def state_version(self) -> int:
        return self._state_version

    @property
    def logical_time(self) -> int:
        return self._logical_time

    def close(self) -> None:
        self._connection.close()

    def _clear_tables(self) -> None:
        for table, _, _ in reversed(_TABLES):
            self._connection.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed names

    def reset(self, task_id: str, seed: int) -> Observation:
        if task_id not in TASK_IDS:
            raise ValueError(f"Unknown task_id: {task_id}")
        task: TravelTaskSpec = (
            book_task_for_seed(seed) if task_id == BOOK_TASK_ID else recovery_task_for_seed(seed)
        )
        self._connection.execute("BEGIN")
        try:
            self._clear_tables()
            if isinstance(task, BookTaskSpec):
                self._seed_book_world(task)
            else:
                self._seed_recovery_world(task)
            self._connection.execute(
                "INSERT INTO travel_metadata(key, value) VALUES ('last_viewed_booking', '')"
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        self._task = task
        self._state_version = 0
        self._logical_time = 0
        self._fault_attempts = {}
        self.last_fault_id = None
        return Observation(
            task_id=task_id,
            seed=seed,
            env_version=ENV_VERSION,
            state_version=0,
            timestamp_logical=0,
            state_hash=self.state_hash(),
            visible_task=self._visible_task(task),
        )

    def _insert_options(
        self,
        flights: tuple[FlightOption, ...],
        hotels: tuple[HotelOption, ...],
    ) -> None:
        self._connection.executemany(
            """
            INSERT INTO flights(
                flight_id, origin, destination, depart_at, arrive_at,
                price_cents, refundable, available_seats
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.flight_id,
                    item.origin,
                    item.destination,
                    item.depart_at,
                    item.arrive_at,
                    item.price_cents,
                    int(item.refundable),
                    item.available_seats,
                )
                for item in flights
            ],
        )
        self._connection.executemany(
            """
            INSERT INTO hotels(
                hotel_id, city, check_in, check_out, price_cents,
                refundable, available_rooms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.hotel_id,
                    item.city,
                    item.check_in,
                    item.check_out,
                    item.price_cents,
                    int(item.refundable),
                    item.available_rooms,
                )
                for item in hotels
            ],
        )

    def _insert_request(
        self,
        *,
        request_id: str,
        user_id: str,
        origin: str,
        destination: str,
        budget_cents: int,
        payment_id: str,
    ) -> None:
        self._connection.execute(
            "INSERT INTO payment_methods(payment_id, user_id, active) VALUES (?, ?, 1)",
            (payment_id, user_id),
        )
        self._connection.execute(
            """
            INSERT INTO booking_requests(
                request_id, user_id, origin, destination, budget_cents, status,
                selected_flight_booking_id, selected_hotel_reservation_id
            ) VALUES (?, ?, ?, ?, ?, 'pending', NULL, NULL)
            """,
            (request_id, user_id, origin, destination, budget_cents),
        )

    def _seed_book_world(self, task: BookTaskSpec) -> None:
        self._insert_options(task.flights, task.hotels)
        self._insert_request(
            request_id=task.request_id,
            user_id=task.user_id,
            origin=task.origin,
            destination=task.destination,
            budget_cents=task.budget_cents,
            payment_id=task.payment_id,
        )

    def _seed_recovery_world(self, task: RecoveryTaskSpec) -> None:
        self._insert_options(
            (task.preferred_flight, task.backup_flight),
            (task.preferred_hotel, task.backup_hotel),
        )
        self._insert_request(
            request_id=task.request_id,
            user_id=task.user_id,
            origin=task.origin,
            destination=task.destination,
            budget_cents=task.budget_cents,
            payment_id=task.payment_id,
        )

    @staticmethod
    def _visible_task(task: TravelTaskSpec) -> dict[str, Any]:
        if isinstance(task, BookTaskSpec):
            return {
                "goal": "book the lowest-cost itinerary satisfying all listed constraints",
                "user_id": task.user_id,
                "request_id": task.request_id,
                "payment_id": task.payment_id,
                "flight_booking_id": task.flight_booking_id,
                "hotel_reservation_id": task.hotel_reservation_id,
                "requirements": {
                    "origin": task.origin,
                    "destination": task.destination,
                    "budget_cents": task.budget_cents,
                    "require_refundable": task.require_refundable,
                },
                "flights": [item.as_dict() for item in task.flights],
                "hotels": [item.as_dict() for item in task.hotels],
            }
        return {
            "goal": (
                "book the preferred bundle; if its flight is unavailable, "
                "cancel the hotel and use the backup bundle"
            ),
            "user_id": task.user_id,
            "request_id": task.request_id,
            "payment_id": task.payment_id,
            "requirements": {
                "origin": task.origin,
                "destination": task.destination,
                "budget_cents": task.budget_cents,
                "require_refundable": True,
            },
            "preferred": {
                "flight": task.preferred_flight.as_dict(),
                "hotel": task.preferred_hotel.as_dict(),
                "flight_booking_id": task.preferred_flight_booking_id,
                "hotel_reservation_id": task.preferred_hotel_reservation_id,
            },
            "backup": {
                "flight": task.backup_flight.as_dict(),
                "hotel": task.backup_hotel.as_dict(),
                "flight_booking_id": task.backup_flight_booking_id,
                "hotel_reservation_id": task.backup_hotel_reservation_id,
            },
        }

    def _rows(self, table: str, order_by: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            f"SELECT * FROM {table} ORDER BY {order_by}"  # noqa: S608 - fixed names
        ).fetchall()
        return [dict(row) for row in rows]

    def export_world(self) -> dict[str, Any]:
        world: dict[str, Any] = {
            "env_version": ENV_VERSION,
            "task_id": self.task.task_id,
            "seed": self.task.seed,
            "task": self.task.as_dict(),
            "state_version": self._state_version,
        }
        for table, order_by, _ in _TABLES:
            world[table] = self._rows(table, order_by)
        return world

    def state_hash(self) -> str:
        return digest_value(self.export_world())

    def snapshot(self) -> SnapshotRef:
        return SnapshotRef.from_value(
            {
                "world": self.export_world(),
                "runtime": {
                    "logical_time": self._logical_time,
                    "fault_attempts": dict(sorted(self._fault_attempts.items())),
                },
            }
        )

    def restore(self, snapshot: SnapshotRef) -> None:
        payload = snapshot.load()
        world = payload["world"]
        runtime = payload["runtime"]
        if world["env_version"] != ENV_VERSION:
            raise ValueError("Snapshot environment version mismatch")
        self._connection.execute("BEGIN")
        try:
            self._clear_tables()
            for table, _, columns in _TABLES:
                records = world[table]
                if not records:
                    continue
                placeholders = ", ".join("?" for _ in columns)
                column_list = ", ".join(columns)
                self._connection.executemany(
                    f"INSERT INTO {table}({column_list}) VALUES ({placeholders})",  # noqa: S608
                    [tuple(record[column] for column in columns) for record in records],
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        task = world["task"]
        self._task = (
            BookTaskSpec.from_dict(task)
            if world["task_id"] == BOOK_TASK_ID
            else RecoveryTaskSpec.from_dict(task)
        )
        self._state_version = world["state_version"]
        self._logical_time = runtime["logical_time"]
        self._fault_attempts = dict(runtime["fault_attempts"])
        self.last_fault_id = None

    def _result(
        self,
        *,
        status: Literal["ok", "retryable_error", "fatal_error", "conflict"],
        before_hash: str,
        value: dict[str, Any] | None = None,
        error_code: str | None = None,
        retry_after_ms: int | None = None,
    ) -> StepResult:
        return StepResult(
            status=status,
            value=value,
            error_code=error_code,
            state_version=self._state_version,
            retry_after_ms=retry_after_ms,
            state_hash_before=before_hash,
            state_hash_after=self.state_hash(),
            timestamp_logical=self._logical_time,
        )

    @staticmethod
    def _request_digest(action: ToolAction) -> str:
        return digest_value(
            {
                "tool_name": action.tool_name,
                "schema_version": action.schema_version,
                "arguments": action.arguments,
            }
        )

    def _idempotency_replay(self, action: ToolAction, before_hash: str) -> StepResult | None:
        if action.idempotency_key is None:
            return None
        if not isinstance(action.idempotency_key, str) or not action.idempotency_key.strip():
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_idempotency_key",
            )
        row = self._connection.execute(
            """
            SELECT tool_name, request_digest, result_json
            FROM idempotency_records WHERE idempotency_key = ?
            """,
            (action.idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row["tool_name"] != action.tool_name or row["request_digest"] != self._request_digest(
            action
        ):
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="idempotency_key_reused",
            )
        return self._result(
            status="ok",
            before_hash=before_hash,
            value=json.loads(row["result_json"]),
        )

    def _insert_idempotency_record(
        self,
        action: ToolAction,
        value: dict[str, Any],
        next_state_version: int,
    ) -> None:
        if action.idempotency_key is None:
            return
        self._connection.execute(
            """
            INSERT INTO idempotency_records(
                idempotency_key, tool_name, request_digest, result_json,
                committed_state_version
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                action.idempotency_key,
                action.tool_name,
                self._request_digest(action),
                canonical_json(value),
                next_state_version,
            ),
        )

    def _validate_action(self, action: ToolAction, before_hash: str) -> StepResult | None:
        if action.schema_version != SCHEMA_VERSION:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="schema_version_unsupported",
            )
        if action.tool_name not in _WRITE_TOOLS | _READ_TOOLS:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="unknown_tool"
            )
        if action.tool_name in _WRITE_TOOLS:
            replay = self._idempotency_replay(action, before_hash)
            if replay is not None:
                return replay
        if (
            action.expected_state_version is not None
            and action.expected_state_version != self._state_version
        ):
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="state_version_conflict",
            )
        return None

    def step(self, action: ToolAction) -> StepResult:
        _ = self.task
        before_hash = self.state_hash()
        self._logical_time += 1
        self.last_fault_id = None
        validation = self._validate_action(action, before_hash)
        if validation is not None:
            return validation
        handlers = {
            "flights.book": self._book_flight,
            "flights.get_booking": self._get_flight_booking,
            "hotels.book": self._book_hotel,
            "hotels.get_reservation": self._get_hotel_reservation,
            "hotels.cancel": self._cancel_hotel,
            "travel.resolve_booking_request": self._resolve_booking_request,
        }
        return handlers[action.tool_name](action, before_hash)

    def _payment_valid(self, payment_id: str, user_id: str) -> bool:
        row = self._connection.execute(
            "SELECT user_id, active FROM payment_methods WHERE payment_id = ?", (payment_id,)
        ).fetchone()
        return bool(row and row["active"] and row["user_id"] == user_id)

    def _book_flight(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        required = {
            "booking_id",
            "flight_id",
            "user_id",
            "payment_id",
            "confirmed_nonrefundable",
        }
        if (
            set(arguments) != required
            or not all(
                isinstance(arguments.get(key), str)
                for key in required - {"confirmed_nonrefundable"}
            )
            or not isinstance(arguments.get("confirmed_nonrefundable"), bool)
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        flight = self._connection.execute(
            "SELECT * FROM flights WHERE flight_id = ?", (arguments["flight_id"],)
        ).fetchone()
        if flight is None or flight["available_seats"] < 1:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="flight_unavailable"
            )
        if not self._payment_valid(arguments["payment_id"], arguments["user_id"]):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="payment_not_authorized"
            )
        if not flight["refundable"] and not arguments["confirmed_nonrefundable"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="confirmation_required"
            )
        if (
            self.fault_mode == "preferred_flight_unavailable"
            and isinstance(self.task, RecoveryTaskSpec)
            and arguments["flight_id"] == self.task.preferred_flight.flight_id
        ):
            self.last_fault_id = "fault.travel.preferred_flight.unavailable"
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="flight_unavailable"
            )
        value = {
            "booked_flight_id": arguments["flight_id"],
            "flight_booking_id": arguments["booking_id"],
            "price_cents": flight["price_cents"],
        }
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            updated = self._connection.execute(
                """
                UPDATE flights SET available_seats = available_seats - 1
                WHERE flight_id = ? AND available_seats >= 1
                """,
                (arguments["flight_id"],),
            )
            if updated.rowcount != 1:
                raise sqlite3.IntegrityError("flight availability changed")
            self._connection.execute(
                """
                INSERT INTO flight_bookings(
                    booking_id, flight_id, user_id, payment_id, status,
                    price_cents, confirmed_nonrefundable
                ) VALUES (?, ?, ?, ?, 'booked', ?, ?)
                """,
                (
                    arguments["booking_id"],
                    arguments["flight_id"],
                    arguments["user_id"],
                    arguments["payment_id"],
                    flight["price_cents"],
                    int(arguments["confirmed_nonrefundable"]),
                ),
            )
            self._insert_idempotency_record(action, value, next_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="flight_booking_transaction_conflict",
            )
        self._state_version = next_version
        if self.fault_mode == "flight_postcommit_timeout_once":
            attempts = self._fault_attempts.get(action.tool_name, 0) + 1
            self._fault_attempts[action.tool_name] = attempts
            if attempts == 1:
                self.last_fault_id = "fault.travel.flight.postcommit_timeout_once"
                return self._result(
                    status="retryable_error",
                    before_hash=before_hash,
                    error_code="tool_timeout_postcommit",
                    retry_after_ms=10,
                )
        return self._result(status="ok", before_hash=before_hash, value=value)

    def _get_flight_booking(self, action: ToolAction, before_hash: str) -> StepResult:
        if set(action.arguments) != {"booking_id"} or not isinstance(
            action.arguments.get("booking_id"), str
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        booking = self._connection.execute(
            "SELECT * FROM flight_bookings WHERE booking_id = ?",
            (action.arguments["booking_id"],),
        ).fetchone()
        if booking is None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="booking_not_found"
            )
        return self._result(status="ok", before_hash=before_hash, value={"booking": dict(booking)})

    def _book_hotel(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        required = {
            "reservation_id",
            "hotel_id",
            "user_id",
            "payment_id",
            "confirmed_nonrefundable",
        }
        if (
            set(arguments) != required
            or not all(
                isinstance(arguments.get(key), str)
                for key in required - {"confirmed_nonrefundable"}
            )
            or not isinstance(arguments.get("confirmed_nonrefundable"), bool)
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        hotel = self._connection.execute(
            "SELECT * FROM hotels WHERE hotel_id = ?", (arguments["hotel_id"],)
        ).fetchone()
        if hotel is None or hotel["available_rooms"] < 1:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="hotel_unavailable"
            )
        if not self._payment_valid(arguments["payment_id"], arguments["user_id"]):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="payment_not_authorized"
            )
        if not hotel["refundable"] and not arguments["confirmed_nonrefundable"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="confirmation_required"
            )
        value = {
            "booked_hotel_id": arguments["hotel_id"],
            "hotel_reservation_id": arguments["reservation_id"],
            "price_cents": hotel["price_cents"],
        }
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            updated = self._connection.execute(
                """
                UPDATE hotels SET available_rooms = available_rooms - 1
                WHERE hotel_id = ? AND available_rooms >= 1
                """,
                (arguments["hotel_id"],),
            )
            if updated.rowcount != 1:
                raise sqlite3.IntegrityError("hotel availability changed")
            self._connection.execute(
                """
                INSERT INTO hotel_reservations(
                    reservation_id, hotel_id, user_id, payment_id, status,
                    price_cents, confirmed_nonrefundable
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    arguments["reservation_id"],
                    arguments["hotel_id"],
                    arguments["user_id"],
                    arguments["payment_id"],
                    hotel["price_cents"],
                    int(arguments["confirmed_nonrefundable"]),
                ),
            )
            self._insert_idempotency_record(action, value, next_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="hotel_booking_transaction_conflict",
            )
        self._state_version = next_version
        return self._result(status="ok", before_hash=before_hash, value=value)

    def _get_hotel_reservation(self, action: ToolAction, before_hash: str) -> StepResult:
        if set(action.arguments) != {"reservation_id"} or not isinstance(
            action.arguments.get("reservation_id"), str
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        reservation = self._connection.execute(
            "SELECT * FROM hotel_reservations WHERE reservation_id = ?",
            (action.arguments["reservation_id"],),
        ).fetchone()
        if reservation is None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="reservation_not_found"
            )
        return self._result(
            status="ok",
            before_hash=before_hash,
            value={"reservation": dict(reservation)},
        )

    def _cancel_hotel(self, action: ToolAction, before_hash: str) -> StepResult:
        if set(action.arguments) != {"reservation_id"} or not isinstance(
            action.arguments.get("reservation_id"), str
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        reservation = self._connection.execute(
            """
            SELECT r.hotel_id, r.status, h.refundable
            FROM hotel_reservations r JOIN hotels h USING(hotel_id)
            WHERE r.reservation_id = ?
            """,
            (action.arguments["reservation_id"],),
        ).fetchone()
        if reservation is None or reservation["status"] != "active":
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="reservation_not_active"
            )
        if not reservation["refundable"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="cancellation_not_allowed"
            )
        value = {"cancelled_reservation_id": action.arguments["reservation_id"]}
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                "UPDATE hotel_reservations SET status = 'cancelled' WHERE reservation_id = ?",
                (action.arguments["reservation_id"],),
            )
            self._connection.execute(
                "UPDATE hotels SET available_rooms = available_rooms + 1 WHERE hotel_id = ?",
                (reservation["hotel_id"],),
            )
            self._insert_idempotency_record(action, value, next_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="conflict", before_hash=before_hash, error_code="cancellation_conflict"
            )
        self._state_version = next_version
        return self._result(status="ok", before_hash=before_hash, value=value)

    def _resolve_booking_request(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        required = {"request_id", "flight_booking_id", "hotel_reservation_id"}
        if set(arguments) != required or not all(
            isinstance(arguments.get(key), str) for key in required
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        request = self._connection.execute(
            "SELECT * FROM booking_requests WHERE request_id = ?", (arguments["request_id"],)
        ).fetchone()
        flight = self._connection.execute(
            """
            SELECT b.user_id, b.status, b.price_cents, f.origin, f.destination, f.arrive_at
            FROM flight_bookings b JOIN flights f USING(flight_id)
            WHERE b.booking_id = ?
            """,
            (arguments["flight_booking_id"],),
        ).fetchone()
        hotel = self._connection.execute(
            """
            SELECT r.user_id, r.status, r.price_cents, h.city, h.check_in
            FROM hotel_reservations r JOIN hotels h USING(hotel_id)
            WHERE r.reservation_id = ?
            """,
            (arguments["hotel_reservation_id"],),
        ).fetchone()
        if request is None or request["status"] != "pending":
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="request_not_pending"
            )
        if (
            flight is None
            or hotel is None
            or flight["status"] != "booked"
            or hotel["status"] != "active"
            or flight["user_id"] != request["user_id"]
            or hotel["user_id"] != request["user_id"]
            or flight["origin"] != request["origin"]
            or flight["destination"] != request["destination"]
            or hotel["city"] != request["destination"]
            or flight["arrive_at"] > hotel["check_in"]
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="itinerary_not_confirmed"
            )
        if flight["price_cents"] + hotel["price_cents"] > request["budget_cents"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="budget_exceeded"
            )
        value = {"resolved_request_id": arguments["request_id"]}
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                """
                UPDATE booking_requests
                SET status = 'resolved', selected_flight_booking_id = ?,
                    selected_hotel_reservation_id = ?
                WHERE request_id = ?
                """,
                (
                    arguments["flight_booking_id"],
                    arguments["hotel_reservation_id"],
                    arguments["request_id"],
                ),
            )
            self._insert_idempotency_record(action, value, next_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="conflict", before_hash=before_hash, error_code="idempotency_key_reused"
            )
        self._state_version = next_version
        return self._result(status="ok", before_hash=before_hash, value=value)
