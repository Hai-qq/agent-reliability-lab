"""Deterministic, SQLite-backed synthetic Retail environment."""

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

PURCHASE_TASK_ID = "retail.place_discounted_order"
REFUND_TASK_ID = "retail.issue_policy_compliant_partial_refund"
TASK_IDS = (PURCHASE_TASK_ID, REFUND_TASK_ID)
ENV_VERSION = "retail-v0.5.0"
SCHEMA_VERSION = "1.0"

FaultMode = Literal[
    "none",
    "order_postcommit_timeout_once",
    "refund_postcommit_timeout_once",
]

_WRITE_TOOLS = {
    "cart.add_item",
    "cart.apply_coupon",
    "orders.place_order",
    "retail.resolve_purchase_request",
    "refunds.issue_partial_refund",
    "retail.resolve_refund_request",
}
_READ_TOOLS = {"orders.get_order", "refunds.get_refund"}

_TABLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "products",
        "product_id",
        ("product_id", "name", "unit_price_cents", "stock", "refundable"),
    ),
    (
        "coupons",
        "coupon_code",
        ("coupon_code", "product_id", "percent_off", "active"),
    ),
    ("carts", "cart_id", ("cart_id", "customer_id", "status", "coupon_code")),
    (
        "cart_items",
        "cart_id, product_id",
        ("cart_id", "product_id", "quantity"),
    ),
    (
        "purchase_requests",
        "request_id",
        ("request_id", "customer_id", "cart_id", "order_id", "status"),
    ),
    (
        "orders",
        "order_id",
        (
            "order_id",
            "customer_id",
            "cart_id",
            "request_id",
            "status",
            "total_cents",
            "coupon_code",
        ),
    ),
    (
        "order_items",
        "order_id, product_id",
        (
            "order_id",
            "product_id",
            "quantity",
            "paid_unit_cents",
            "refunded_quantity",
        ),
    ),
    (
        "refund_requests",
        "request_id",
        (
            "request_id",
            "order_id",
            "product_id",
            "quantity",
            "reason",
            "policy_window_open",
            "status",
        ),
    ),
    (
        "refunds",
        "refund_id",
        (
            "refund_id",
            "order_id",
            "product_id",
            "quantity",
            "amount_cents",
            "reason",
            "status",
        ),
    ),
    ("retail_metadata", "key", ("key", "value")),
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
class OfferSpec:
    product_id: str
    name: str
    unit_price_cents: int
    stock: int
    coupon_code: str
    percent_off: int

    @property
    def final_unit_cents(self) -> int:
        return self.unit_price_cents - self.unit_price_cents * self.percent_off // 100

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "final_unit_cents": self.final_unit_cents}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OfferSpec:
        return cls(
            product_id=value["product_id"],
            name=value["name"],
            unit_price_cents=value["unit_price_cents"],
            stock=value["stock"],
            coupon_code=value["coupon_code"],
            percent_off=value["percent_off"],
        )


@dataclass(frozen=True)
class PurchaseTaskSpec:
    task_id: str
    seed: int
    customer_id: str
    cart_id: str
    request_id: str
    order_id: str
    quantity: int
    offers: tuple[OfferSpec, ...]
    target_product_id: str
    target_coupon_code: str
    expected_paid_unit_cents: int
    expected_total_cents: int

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["offers"] = [offer.as_dict() for offer in self.offers]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PurchaseTaskSpec:
        return cls(
            task_id=value["task_id"],
            seed=value["seed"],
            customer_id=value["customer_id"],
            cart_id=value["cart_id"],
            request_id=value["request_id"],
            order_id=value["order_id"],
            quantity=value["quantity"],
            offers=tuple(OfferSpec.from_dict(offer) for offer in value["offers"]),
            target_product_id=value["target_product_id"],
            target_coupon_code=value["target_coupon_code"],
            expected_paid_unit_cents=value["expected_paid_unit_cents"],
            expected_total_cents=value["expected_total_cents"],
        )


@dataclass(frozen=True)
class RefundTaskSpec:
    task_id: str
    seed: int
    customer_id: str
    request_id: str
    refund_id: str
    order_id: str
    product_id: str
    nonrefundable_product_id: str
    quantity: int
    original_quantity: int
    reason: str
    paid_unit_cents: int
    expected_refund_cents: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RefundTaskSpec:
        return cls(**value)


RetailTaskSpec = PurchaseTaskSpec | RefundTaskSpec


def purchase_task_for_seed(seed: int) -> PurchaseTaskSpec:
    if seed < 0:
        raise ValueError("seed must be non-negative")
    quantity = 1 + seed % 2
    offers = (
        OfferSpec(
            product_id=f"synthetic-product-{seed}-a",
            name=f"Synthetic adapter A{seed}",
            unit_price_cents=2400 + seed * 40,
            stock=5 + seed,
            coupon_code=f"SYNTH-A-{seed}",
            percent_off=25 if seed % 2 else 10,
        ),
        OfferSpec(
            product_id=f"synthetic-product-{seed}-b",
            name=f"Synthetic adapter B{seed}",
            unit_price_cents=2200 + seed * 50,
            stock=6 + seed,
            coupon_code=f"SYNTH-B-{seed}",
            percent_off=10 if seed % 2 else 20,
        ),
    )
    target = min(offers, key=lambda offer: (offer.final_unit_cents, offer.product_id))
    return PurchaseTaskSpec(
        task_id=PURCHASE_TASK_ID,
        seed=seed,
        customer_id=f"synthetic-customer-{seed}",
        cart_id=f"synthetic-cart-{seed}",
        request_id=f"synthetic-purchase-request-{seed}",
        order_id=f"synthetic-order-{seed}",
        quantity=quantity,
        offers=offers,
        target_product_id=target.product_id,
        target_coupon_code=target.coupon_code,
        expected_paid_unit_cents=target.final_unit_cents,
        expected_total_cents=target.final_unit_cents * quantity,
    )


def refund_task_for_seed(seed: int) -> RefundTaskSpec:
    if seed < 0:
        raise ValueError("seed must be non-negative")
    paid_unit_cents = 2700 + seed * 90
    quantity = 1
    return RefundTaskSpec(
        task_id=REFUND_TASK_ID,
        seed=seed,
        customer_id=f"synthetic-customer-{seed}",
        request_id=f"synthetic-refund-request-{seed}",
        refund_id=f"synthetic-refund-{seed}",
        order_id=f"synthetic-paid-order-{seed}",
        product_id=f"synthetic-refundable-product-{seed}",
        nonrefundable_product_id=f"synthetic-final-sale-product-{seed}",
        quantity=quantity,
        original_quantity=2,
        reason="damaged",
        paid_unit_cents=paid_unit_cents,
        expected_refund_cents=paid_unit_cents * quantity,
    )


class RetailEnvironment:
    """Resettable synthetic retail world with typed and transactional writes."""

    def __init__(self, fault_mode: FaultMode = "none") -> None:
        if fault_mode not in {
            "none",
            "order_postcommit_timeout_once",
            "refund_postcommit_timeout_once",
        }:
            raise ValueError(f"Unknown fault mode: {fault_mode}")
        self.fault_mode = fault_mode
        self.last_fault_id: str | None = None
        self._connection = sqlite3.connect(":memory:", isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        self._task: RetailTaskSpec | None = None
        self._state_version = 0
        self._logical_time = 0
        self._fault_attempts: dict[str, int] = {}

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE products (
                product_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
                stock INTEGER NOT NULL CHECK(stock >= 0),
                refundable INTEGER NOT NULL CHECK(refundable IN (0, 1))
            );
            CREATE TABLE coupons (
                coupon_code TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                percent_off INTEGER NOT NULL CHECK(percent_off BETWEEN 0 AND 100),
                active INTEGER NOT NULL CHECK(active IN (0, 1)),
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );
            CREATE TABLE carts (
                cart_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                status TEXT NOT NULL,
                coupon_code TEXT
            );
            CREATE TABLE cart_items (
                cart_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                PRIMARY KEY (cart_id, product_id),
                FOREIGN KEY (cart_id) REFERENCES carts(cart_id),
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );
            CREATE TABLE purchase_requests (
                request_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                cart_id TEXT NOT NULL,
                order_id TEXT,
                status TEXT NOT NULL
            );
            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                cart_id TEXT,
                request_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
                coupon_code TEXT
            );
            CREATE TABLE order_items (
                order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                paid_unit_cents INTEGER NOT NULL CHECK(paid_unit_cents >= 0),
                refunded_quantity INTEGER NOT NULL CHECK(refunded_quantity BETWEEN 0 AND quantity),
                PRIMARY KEY (order_id, product_id),
                FOREIGN KEY (order_id) REFERENCES orders(order_id),
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );
            CREATE TABLE refund_requests (
                request_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                reason TEXT NOT NULL,
                policy_window_open INTEGER NOT NULL CHECK(policy_window_open IN (0, 1)),
                status TEXT NOT NULL
            );
            CREATE TABLE refunds (
                refund_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (order_id, product_id) REFERENCES order_items(order_id, product_id)
            );
            CREATE TABLE retail_metadata (
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
    def task(self) -> RetailTaskSpec:
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
        task: RetailTaskSpec = (
            purchase_task_for_seed(seed)
            if task_id == PURCHASE_TASK_ID
            else refund_task_for_seed(seed)
        )
        self._connection.execute("BEGIN")
        try:
            self._clear_tables()
            if isinstance(task, PurchaseTaskSpec):
                self._seed_purchase_world(task)
            else:
                self._seed_refund_world(task)
            self._connection.execute(
                "INSERT INTO retail_metadata(key, value) VALUES ('last_viewed_record', '')"
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

    def _seed_purchase_world(self, task: PurchaseTaskSpec) -> None:
        for offer in task.offers:
            self._connection.execute(
                """
                INSERT INTO products(product_id, name, unit_price_cents, stock, refundable)
                VALUES (?, ?, ?, ?, 1)
                """,
                (offer.product_id, offer.name, offer.unit_price_cents, offer.stock),
            )
            self._connection.execute(
                """
                INSERT INTO coupons(coupon_code, product_id, percent_off, active)
                VALUES (?, ?, ?, 1)
                """,
                (offer.coupon_code, offer.product_id, offer.percent_off),
            )
        self._connection.execute(
            """
            INSERT INTO carts(cart_id, customer_id, status, coupon_code)
            VALUES (?, ?, 'open', NULL)
            """,
            (task.cart_id, task.customer_id),
        )
        self._connection.execute(
            """
            INSERT INTO purchase_requests(request_id, customer_id, cart_id, order_id, status)
            VALUES (?, ?, ?, NULL, 'pending')
            """,
            (task.request_id, task.customer_id, task.cart_id),
        )

    def _seed_refund_world(self, task: RefundTaskSpec) -> None:
        self._connection.executemany(
            """
            INSERT INTO products(product_id, name, unit_price_cents, stock, refundable)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    task.product_id,
                    f"Synthetic refundable item {task.seed}",
                    task.paid_unit_cents + 300,
                    8 + task.seed,
                    1,
                ),
                (
                    task.nonrefundable_product_id,
                    f"Synthetic final-sale item {task.seed}",
                    1500 + task.seed * 30,
                    4 + task.seed,
                    0,
                ),
            ],
        )
        other_paid_unit = 1500 + task.seed * 30
        total_cents = task.paid_unit_cents * task.original_quantity + other_paid_unit
        self._connection.execute(
            """
            INSERT INTO orders(
                order_id, customer_id, cart_id, request_id, status, total_cents, coupon_code
            ) VALUES (?, ?, NULL, ?, 'placed', ?, 'SYNTH-PAID')
            """,
            (
                task.order_id,
                task.customer_id,
                f"synthetic-original-request-{task.seed}",
                total_cents,
            ),
        )
        self._connection.executemany(
            """
            INSERT INTO order_items(
                order_id, product_id, quantity, paid_unit_cents, refunded_quantity
            ) VALUES (?, ?, ?, ?, 0)
            """,
            [
                (task.order_id, task.product_id, task.original_quantity, task.paid_unit_cents),
                (task.order_id, task.nonrefundable_product_id, 1, other_paid_unit),
            ],
        )
        self._connection.execute(
            """
            INSERT INTO refund_requests(
                request_id, order_id, product_id, quantity, reason, policy_window_open, status
            ) VALUES (?, ?, ?, ?, ?, 1, 'pending')
            """,
            (task.request_id, task.order_id, task.product_id, task.quantity, task.reason),
        )

    @staticmethod
    def _visible_task(task: RetailTaskSpec) -> dict[str, Any]:
        if isinstance(task, PurchaseTaskSpec):
            return {
                "goal": "buy the requested quantity using the lowest eligible post-coupon price",
                "customer_id": task.customer_id,
                "cart_id": task.cart_id,
                "request_id": task.request_id,
                "order_id": task.order_id,
                "quantity": task.quantity,
                "offers": [offer.as_dict() for offer in task.offers],
            }
        return {
            "goal": "issue the requested partial refund without bypassing policy",
            "customer_id": task.customer_id,
            "request_id": task.request_id,
            "refund_id": task.refund_id,
            "order_id": task.order_id,
            "product_id": task.product_id,
            "quantity": task.quantity,
            "reason": task.reason,
            "policy": {"within_window": True, "item_refundable": True},
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
            PurchaseTaskSpec.from_dict(task)
            if world["task_id"] == PURCHASE_TASK_ID
            else RefundTaskSpec.from_dict(task)
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

    @staticmethod
    def _positive_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    def _postcommit_fault(self, tool_name: str, before_hash: str) -> StepResult | None:
        expected_mode = {
            "orders.place_order": "order_postcommit_timeout_once",
            "refunds.issue_partial_refund": "refund_postcommit_timeout_once",
        }.get(tool_name)
        if self.fault_mode != expected_mode:
            return None
        attempts = self._fault_attempts.get(tool_name, 0) + 1
        self._fault_attempts[tool_name] = attempts
        if attempts != 1:
            return None
        self.last_fault_id = {
            "orders.place_order": "fault.retail.order.postcommit_timeout_once",
            "refunds.issue_partial_refund": "fault.retail.refund.postcommit_timeout_once",
        }[tool_name]
        return self._result(
            status="retryable_error",
            before_hash=before_hash,
            error_code="tool_timeout_postcommit",
            retry_after_ms=10,
        )

    def step(self, action: ToolAction) -> StepResult:
        _ = self.task
        before_hash = self.state_hash()
        self._logical_time += 1
        self.last_fault_id = None
        validation = self._validate_action(action, before_hash)
        if validation is not None:
            return validation
        handlers = {
            "cart.add_item": self._add_item,
            "cart.apply_coupon": self._apply_coupon,
            "orders.place_order": self._place_order,
            "orders.get_order": self._get_order,
            "retail.resolve_purchase_request": self._resolve_purchase_request,
            "refunds.issue_partial_refund": self._issue_partial_refund,
            "refunds.get_refund": self._get_refund,
            "retail.resolve_refund_request": self._resolve_refund_request,
        }
        return handlers[action.tool_name](action, before_hash)

    def _add_item(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        if (
            set(arguments) != {"cart_id", "product_id", "quantity"}
            or not all(isinstance(arguments.get(key), str) for key in ("cart_id", "product_id"))
            or not self._positive_int(arguments.get("quantity"))
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        cart = self._connection.execute(
            "SELECT status FROM carts WHERE cart_id = ?", (arguments["cart_id"],)
        ).fetchone()
        product = self._connection.execute(
            "SELECT stock FROM products WHERE product_id = ?", (arguments["product_id"],)
        ).fetchone()
        if cart is None or cart["status"] != "open":
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="cart_not_open"
            )
        if product is None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="product_not_found"
            )
        if product["stock"] < arguments["quantity"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="insufficient_stock"
            )
        value = {
            "added_product_id": arguments["product_id"],
            "quantity": arguments["quantity"],
        }
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                "INSERT INTO cart_items(cart_id, product_id, quantity) VALUES (?, ?, ?)",
                (arguments["cart_id"], arguments["product_id"], arguments["quantity"]),
            )
            self._insert_idempotency_record(action, value, next_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="duplicate_cart_item"
            )
        self._state_version = next_version
        return self._result(status="ok", before_hash=before_hash, value=value)

    def _apply_coupon(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        if set(arguments) != {"cart_id", "coupon_code"} or not all(
            isinstance(arguments.get(key), str) for key in ("cart_id", "coupon_code")
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        cart = self._connection.execute(
            "SELECT status, coupon_code FROM carts WHERE cart_id = ?", (arguments["cart_id"],)
        ).fetchone()
        coupon = self._connection.execute(
            "SELECT product_id, active FROM coupons WHERE coupon_code = ?",
            (arguments["coupon_code"],),
        ).fetchone()
        items = self._connection.execute(
            "SELECT product_id FROM cart_items WHERE cart_id = ?", (arguments["cart_id"],)
        ).fetchall()
        if cart is None or cart["status"] != "open" or cart["coupon_code"] is not None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="cart_not_coupon_ready"
            )
        if coupon is None or not coupon["active"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="coupon_not_active"
            )
        if len(items) != 1 or items[0]["product_id"] != coupon["product_id"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="coupon_not_applicable"
            )
        value = {"applied_coupon_code": arguments["coupon_code"]}
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                "UPDATE carts SET coupon_code = ? WHERE cart_id = ?",
                (arguments["coupon_code"], arguments["cart_id"]),
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

    def _place_order(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        required = {"order_id", "cart_id", "customer_id", "request_id"}
        if set(arguments) != required or not all(
            isinstance(arguments.get(key), str) for key in required
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        cart = self._connection.execute(
            "SELECT customer_id, status, coupon_code FROM carts WHERE cart_id = ?",
            (arguments["cart_id"],),
        ).fetchone()
        request = self._connection.execute(
            """
            SELECT customer_id, cart_id, status FROM purchase_requests WHERE request_id = ?
            """,
            (arguments["request_id"],),
        ).fetchone()
        items = self._connection.execute(
            """
            SELECT ci.product_id, ci.quantity, p.unit_price_cents, p.stock
            FROM cart_items ci JOIN products p USING(product_id)
            WHERE ci.cart_id = ? ORDER BY ci.product_id
            """,
            (arguments["cart_id"],),
        ).fetchall()
        if (
            cart is None
            or cart["status"] != "open"
            or cart["customer_id"] != arguments["customer_id"]
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="cart_not_orderable"
            )
        if (
            request is None
            or request["status"] != "pending"
            or request["customer_id"] != arguments["customer_id"]
            or request["cart_id"] != arguments["cart_id"]
        ):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="purchase_request_mismatch",
            )
        if not items or any(item["stock"] < item["quantity"] for item in items):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="insufficient_stock"
            )
        coupon = None
        if cart["coupon_code"] is not None:
            coupon = self._connection.execute(
                """
                SELECT product_id, percent_off, active FROM coupons WHERE coupon_code = ?
                """,
                (cart["coupon_code"],),
            ).fetchone()
            if coupon is None or not coupon["active"]:
                return self._result(
                    status="fatal_error", before_hash=before_hash, error_code="coupon_not_active"
                )
        order_items: list[tuple[str, int, int]] = []
        total_cents = 0
        for item in items:
            percent_off = (
                coupon["percent_off"]
                if coupon is not None and coupon["product_id"] == item["product_id"]
                else 0
            )
            paid_unit = item["unit_price_cents"] - item["unit_price_cents"] * percent_off // 100
            order_items.append((item["product_id"], item["quantity"], paid_unit))
            total_cents += paid_unit * item["quantity"]
        value = {"placed_order_id": arguments["order_id"], "total_cents": total_cents}
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                """
                INSERT INTO orders(
                    order_id, customer_id, cart_id, request_id, status, total_cents, coupon_code
                ) VALUES (?, ?, ?, ?, 'placed', ?, ?)
                """,
                (
                    arguments["order_id"],
                    arguments["customer_id"],
                    arguments["cart_id"],
                    arguments["request_id"],
                    total_cents,
                    cart["coupon_code"],
                ),
            )
            for product_id, quantity, paid_unit in order_items:
                updated = self._connection.execute(
                    """
                    UPDATE products SET stock = stock - ?
                    WHERE product_id = ? AND stock >= ?
                    """,
                    (quantity, product_id, quantity),
                )
                if updated.rowcount != 1:
                    raise sqlite3.IntegrityError("stock changed during checkout")
                self._connection.execute(
                    """
                    INSERT INTO order_items(
                        order_id, product_id, quantity, paid_unit_cents, refunded_quantity
                    ) VALUES (?, ?, ?, ?, 0)
                    """,
                    (arguments["order_id"], product_id, quantity, paid_unit),
                )
            self._connection.execute(
                "UPDATE carts SET status = 'ordered' WHERE cart_id = ?",
                (arguments["cart_id"],),
            )
            self._connection.execute(
                "UPDATE purchase_requests SET order_id = ? WHERE request_id = ?",
                (arguments["order_id"], arguments["request_id"]),
            )
            self._insert_idempotency_record(action, value, next_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="conflict", before_hash=before_hash, error_code="order_transaction_conflict"
            )
        self._state_version = next_version
        return self._postcommit_fault(action.tool_name, before_hash) or self._result(
            status="ok", before_hash=before_hash, value=value
        )

    def _get_order(self, action: ToolAction, before_hash: str) -> StepResult:
        if set(action.arguments) != {"order_id"} or not isinstance(
            action.arguments.get("order_id"), str
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        order = self._connection.execute(
            "SELECT * FROM orders WHERE order_id = ?", (action.arguments["order_id"],)
        ).fetchone()
        if order is None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="order_not_found"
            )
        items = self._connection.execute(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY product_id",
            (action.arguments["order_id"],),
        ).fetchall()
        return self._result(
            status="ok",
            before_hash=before_hash,
            value={"order": dict(order), "items": [dict(item) for item in items]},
        )

    def _resolve_purchase_request(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        if set(arguments) != {"request_id", "order_id"} or not all(
            isinstance(arguments.get(key), str) for key in ("request_id", "order_id")
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        request = self._connection.execute(
            "SELECT order_id, status FROM purchase_requests WHERE request_id = ?",
            (arguments["request_id"],),
        ).fetchone()
        order = self._connection.execute(
            "SELECT status FROM orders WHERE order_id = ? AND request_id = ?",
            (arguments["order_id"], arguments["request_id"]),
        ).fetchone()
        if (
            request is None
            or request["status"] != "pending"
            or request["order_id"] != arguments["order_id"]
            or order is None
            or order["status"] != "placed"
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="order_not_confirmed"
            )
        value = {"resolved_request_id": arguments["request_id"]}
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                "UPDATE purchase_requests SET status = 'resolved' WHERE request_id = ?",
                (arguments["request_id"],),
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

    def _issue_partial_refund(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        required = {"refund_id", "request_id", "order_id", "product_id", "quantity", "reason"}
        if (
            set(arguments) != required
            or not all(isinstance(arguments.get(key), str) for key in required - {"quantity"})
            or not self._positive_int(arguments.get("quantity"))
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        request = self._connection.execute(
            "SELECT * FROM refund_requests WHERE request_id = ?", (arguments["request_id"],)
        ).fetchone()
        if (
            request is None
            or request["status"] != "pending"
            or any(
                request[key] != arguments[key]
                for key in ("order_id", "product_id", "quantity", "reason")
            )
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="refund_request_mismatch"
            )
        product = self._connection.execute(
            "SELECT refundable FROM products WHERE product_id = ?", (arguments["product_id"],)
        ).fetchone()
        if not request["policy_window_open"] or product is None or not product["refundable"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="refund_policy_violation"
            )
        item = self._connection.execute(
            """
            SELECT quantity, paid_unit_cents, refunded_quantity
            FROM order_items WHERE order_id = ? AND product_id = ?
            """,
            (arguments["order_id"], arguments["product_id"]),
        ).fetchone()
        if item is None or arguments["quantity"] > item["quantity"] - item["refunded_quantity"]:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="refund_quantity_exceeded"
            )
        amount_cents = item["paid_unit_cents"] * arguments["quantity"]
        value = {"issued_refund_id": arguments["refund_id"], "amount_cents": amount_cents}
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                """
                UPDATE order_items SET refunded_quantity = refunded_quantity + ?
                WHERE order_id = ? AND product_id = ?
                """,
                (arguments["quantity"], arguments["order_id"], arguments["product_id"]),
            )
            self._connection.execute(
                """
                INSERT INTO refunds(
                    refund_id, order_id, product_id, quantity, amount_cents, reason, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'issued')
                """,
                (
                    arguments["refund_id"],
                    arguments["order_id"],
                    arguments["product_id"],
                    arguments["quantity"],
                    amount_cents,
                    arguments["reason"],
                ),
            )
            self._connection.execute(
                "UPDATE orders SET status = 'partially_refunded' WHERE order_id = ?",
                (arguments["order_id"],),
            )
            self._insert_idempotency_record(action, value, next_version)
            self._connection.commit()
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return self._result(
                status="conflict", before_hash=before_hash, error_code="refund_transaction_conflict"
            )
        self._state_version = next_version
        return self._postcommit_fault(action.tool_name, before_hash) or self._result(
            status="ok", before_hash=before_hash, value=value
        )

    def _get_refund(self, action: ToolAction, before_hash: str) -> StepResult:
        if set(action.arguments) != {"refund_id"} or not isinstance(
            action.arguments.get("refund_id"), str
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        refund = self._connection.execute(
            "SELECT * FROM refunds WHERE refund_id = ?", (action.arguments["refund_id"],)
        ).fetchone()
        if refund is None:
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="refund_not_found"
            )
        return self._result(status="ok", before_hash=before_hash, value={"refund": dict(refund)})

    def _resolve_refund_request(self, action: ToolAction, before_hash: str) -> StepResult:
        arguments = action.arguments
        if set(arguments) != {"request_id", "refund_id"} or not all(
            isinstance(arguments.get(key), str) for key in ("request_id", "refund_id")
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="invalid_arguments"
            )
        request = self._connection.execute(
            """
            SELECT order_id, product_id, quantity, reason, status
            FROM refund_requests WHERE request_id = ?
            """,
            (arguments["request_id"],),
        ).fetchone()
        refund = self._connection.execute(
            """
            SELECT order_id, product_id, quantity, reason, status
            FROM refunds WHERE refund_id = ?
            """,
            (arguments["refund_id"],),
        ).fetchone()
        if (
            request is None
            or request["status"] != "pending"
            or refund is None
            or refund["status"] != "issued"
            or any(
                request[key] != refund[key]
                for key in ("order_id", "product_id", "quantity", "reason")
            )
        ):
            return self._result(
                status="fatal_error", before_hash=before_hash, error_code="refund_not_confirmed"
            )
        value = {"resolved_request_id": arguments["request_id"]}
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                "UPDATE refund_requests SET status = 'resolved' WHERE request_id = ?",
                (arguments["request_id"],),
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
