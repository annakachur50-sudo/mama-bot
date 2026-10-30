"""Telegram Payments helpers and durable wardrobe entitlements."""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Callable

from aiogram.types import LabeledPrice


PAYMENT_AMOUNT = 4900
PAYMENT_CURRENCY = "RUB"
PAYMENT_TITLE = "Персональный подбор гардероба"
PAYMENT_DESCRIPTION = (
    "Полный разбор и индивидуальный подбор капсулы "
    "с учётом твоего цветотипа и предпочтений ✨"
)
PAYMENT_START_PARAMETER = "wardrobe-styling-49"


class PaymentStorageUnavailable(RuntimeError):
    pass


def payment_provider_token() -> str | None:
    return os.getenv("PAYMENT_PROVIDER_TOKEN") or None


def build_invoice_parameters(provider_token: str | None, payload: str) -> dict | None:
    """Build Telegram invoice arguments; never create an invoice without a provider token."""
    if not provider_token:
        return None
    return {
        "title": PAYMENT_TITLE,
        "description": PAYMENT_DESCRIPTION,
        "payload": payload,
        "provider_token": provider_token,
        "currency": PAYMENT_CURRENCY,
        "prices": [LabeledPrice(label="Подбор гардероба", amount=PAYMENT_AMOUNT)],
        "start_parameter": PAYMENT_START_PARAMETER,
    }


def make_order_id() -> str:
    return str(uuid.uuid4())


def make_payment_payload(order_id: str) -> str:
    return f"wardrobe:{order_id}"


def _connect():
    dsn = os.getenv("SUPABASE_DB_URL")
    if not dsn:
        raise PaymentStorageUnavailable("payment database is not configured")
    try:
        import psycopg
        return psycopg.connect(dsn, connect_timeout=4, sslmode="require")
    except Exception as error:
        raise PaymentStorageUnavailable(type(error).__name__) from None


def _is_sqlite(connection) -> bool:
    return isinstance(connection, sqlite3.Connection)


def _execute(connection, query: str, params=()):
    if _is_sqlite(connection):
        query = query.replace("public.", "")
    else:
        query = query.replace("?", "%s")
    return connection.execute(query, params)


def _row_dict(cursor, row):
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return {column.name if hasattr(column, "name") else column[0]: value
            for column, value in zip(cursor.description, row)}


def ensure_payment_schema(connection_factory: Callable = _connect) -> None:
    connection = connection_factory()
    try:
        with connection:
            _execute(connection, """
                CREATE TABLE IF NOT EXISTS public.wardrobe_orders (
                    order_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL UNIQUE,
                    telegram_user_id BIGINT NOT NULL,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    paid_at TIMESTAMPTZ,
                    telegram_payment_charge_id TEXT UNIQUE,
                    provider_payment_charge_id TEXT
                )
            """)
            _execute(connection, """
                CREATE UNIQUE INDEX IF NOT EXISTS wardrobe_one_pending_order_per_user
                ON public.wardrobe_orders (telegram_user_id)
                WHERE status = 'pending'
            """)
            _execute(connection, """
                CREATE TABLE IF NOT EXISTS public.wardrobe_access (
                    telegram_user_id BIGINT PRIMARY KEY,
                    order_id TEXT NOT NULL UNIQUE,
                    granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
    finally:
        # psycopg connections close on context exit; sqlite test connections stay open.


def _fetch_order(connection, payload: str, for_update: bool = False):
    query = """
        SELECT order_id, payload, telegram_user_id, amount, currency, status,
               telegram_payment_charge_id, provider_payment_charge_id, paid_at
        FROM public.wardrobe_orders
        WHERE payload = ?
    """
    if for_update and not _is_sqlite(connection):
        query += " FOR UPDATE"
    cursor = _execute(connection, query, (payload,))
    return _row_dict(cursor, cursor.fetchone())


def find_order_by_payload(payload: str, connection_factory: Callable = _connect):
    ensure_payment_schema(connection_factory)
    connection = connection_factory()
    try:
        return _fetch_order(connection, payload)
    finally:
        if not _is_sqlite(connection):
            connection.close()


def create_pending_order(telegram_user_id: int, connection_factory: Callable = _connect):
    ensure_payment_schema(connection_factory)
    connection = connection_factory()
    try:
        with connection:
            access = _execute(connection, """
                SELECT 1 FROM public.wardrobe_access WHERE telegram_user_id = ?
            """, (telegram_user_id,)).fetchone()
            if access:
                return None
            cursor = _execute(connection, """
                SELECT order_id, payload, telegram_user_id, amount, currency, status,
                       telegram_payment_charge_id, provider_payment_charge_id, paid_at
                FROM public.wardrobe_orders
                WHERE telegram_user_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
            """, (telegram_user_id,))
            existing = _row_dict(cursor, cursor.fetchone())
            if existing:
                return existing
            order_id = make_order_id()
            payload = make_payment_payload(order_id)
            _execute(connection, """
                INSERT INTO public.wardrobe_orders
                    (order_id, payload, telegram_user_id, amount, currency, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                ON CONFLICT DO NOTHING
            """, (order_id, payload, telegram_user_id, PAYMENT_AMOUNT, PAYMENT_CURRENCY))
            created = _fetch_order(connection, payload)
            if created:
                return created
            # Another callback may have inserted the user's pending order concurrently.
            cursor = _execute(connection, """
                SELECT order_id, payload, telegram_user_id, amount, currency, status,
                       telegram_payment_charge_id, provider_payment_charge_id, paid_at
                FROM public.wardrobe_orders
                WHERE telegram_user_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
            """, (telegram_user_id,))
            return _row_dict(cursor, cursor.fetchone())
    finally:
        if not _is_sqlite(connection):
            connection.close()


def validate_pre_checkout(order: dict | None, telegram_user_id: int,
                          total_amount: int, currency: str) -> tuple[bool, str]:
    if order is None:
        return False, "Заказ не найден. Открой оформление ещё раз."
    if int(order["telegram_user_id"]) != int(telegram_user_id):
        return False, "Этот заказ оформлен другим пользователем."
    if int(order["amount"]) != PAYMENT_AMOUNT or int(total_amount) != PAYMENT_AMOUNT:
        return False, "Сумма заказа не совпадает. Создай новый заказ."
    if order["currency"] != PAYMENT_CURRENCY or currency != PAYMENT_CURRENCY:
        return False, "Валюта заказа не совпадает. Создай новый заказ."
    if order["status"] != "pending" or order.get("telegram_payment_charge_id"):
        return False, "Этот заказ уже оплачен или больше не активен."
    return True, ""


def record_successful_payment(
    payload: str,
    telegram_user_id: int,
    total_amount: int,
    currency: str,
    telegram_payment_charge_id: str,
    provider_payment_charge_id: str | None,
    connection_factory: Callable = _connect,
) -> bool:
    """Atomically mark a valid pending order paid and grant access exactly once."""
    ensure_payment_schema(connection_factory)
    connection = connection_factory()
    try:
        with connection:
            order = _fetch_order(connection, payload, for_update=True)
            valid, _ = validate_pre_checkout(order, telegram_user_id, total_amount, currency)
            if not valid:
                return False
            paid_at = datetime.now(timezone.utc).isoformat()
            updated = _execute(connection, """
                UPDATE public.wardrobe_orders
                SET status = 'paid', paid_at = ?, telegram_payment_charge_id = ?,
                    provider_payment_charge_id = ?
                WHERE order_id = ? AND status = 'pending'
            """, (paid_at, telegram_payment_charge_id, provider_payment_charge_id,
                  order["order_id"]))
            if updated.rowcount != 1:
                return False
            # The primary key makes entitlement grant idempotent across retries/restarts.
            _execute(connection, """
                INSERT INTO public.wardrobe_access (telegram_user_id, order_id)
                VALUES (?, ?)
                ON CONFLICT (telegram_user_id) DO NOTHING
            """, (telegram_user_id, order["order_id"]))
            return True
    finally:
        if not _is_sqlite(connection):
            connection.close()


def has_wardrobe_access(telegram_user_id: int, connection_factory: Callable = _connect) -> bool:
    ensure_payment_schema(connection_factory)
    connection = connection_factory()
    try:
        row = _execute(connection, """
            SELECT 1 FROM public.wardrobe_access WHERE telegram_user_id = ?
        """, (telegram_user_id,)).fetchone()
        return row is not None
    finally:
        if not _is_sqlite(connection):
            connection.close()
