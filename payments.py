"""YooKassa Web-acquiring integration for the paid wardrobe feature.

All payment confirmations are verified against YooKassa's authenticated API.
The incoming webhook body is never trusted as proof of payment.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any


PAYMENT_AMOUNT = Decimal("49.00")
PAYMENT_CURRENCY = "RUB"
YOOKASSA_API_URL = "https://api.yookassa.ru/v3"


class PaymentConfigurationError(RuntimeError):
    pass


class PaymentValidationError(ValueError):
    pass


def _db_connect():
    import psycopg

    dsn = os.getenv("SUPABASE_DB_URL")
    if not dsn:
        raise PaymentConfigurationError("SUPABASE_DB_URL is not configured")
    return psycopg.connect(dsn, connect_timeout=5)


def init_payment_tables_sync() -> None:
    with _db_connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS public.stylist_payment_orders (
                order_id UUID PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL,
                amount NUMERIC(10, 2) NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                payment_id TEXT UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                paid_at TIMESTAMPTZ
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS public.care_orders (
                order_id UUID PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL,
                mode TEXT,
                amount NUMERIC(10, 2) NOT NULL DEFAULT 99.00,
                currency TEXT NOT NULL DEFAULT 'RUB',
                status TEXT NOT NULL DEFAULT 'pending',
                payment_id TEXT UNIQUE,
                answers JSONB NOT NULL DEFAULT '{}'::jsonb,
                result_text TEXT,
                result_status TEXT NOT NULL DEFAULT 'pending',
                photo_consent_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                paid_at TIMESTAMPTZ
            )
        """)
        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS care_orders_one_pending_per_user
            ON public.care_orders (telegram_user_id)
            WHERE status = 'pending'
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS public.care_access (
                telegram_user_id BIGINT PRIMARY KEY,
                order_id UUID NOT NULL UNIQUE REFERENCES public.care_orders(order_id),
                granted_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS public.stylist_access (
                telegram_user_id BIGINT PRIMARY KEY,
                payment_id TEXT NOT NULL,
                paid_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)


def create_pending_order_sync(telegram_user_id: int) -> str:
    order_id = str(uuid.uuid4())
    with _db_connect() as connection:
        connection.execute("""
            INSERT INTO public.stylist_payment_orders
                (order_id, telegram_user_id, amount, currency, status)
            VALUES (%s, %s, %s, %s, 'pending')
        """, (order_id, telegram_user_id, PAYMENT_AMOUNT, PAYMENT_CURRENCY))
    return order_id


def save_payment_id_sync(order_id: str, payment_id: str) -> None:
    with _db_connect() as connection:
        connection.execute("""
            UPDATE public.stylist_payment_orders
            SET payment_id = %s
            WHERE order_id = %s::uuid AND status = 'pending'
        """, (payment_id, order_id))


def mark_order_failed_sync(order_id: str) -> None:
    with _db_connect() as connection:
        connection.execute("""
            UPDATE public.stylist_payment_orders
            SET status = 'payment_creation_failed'
            WHERE order_id = %s::uuid AND status = 'pending'
        """, (order_id,))


def has_stylist_access_sync(telegram_user_id: int) -> bool:
    with _db_connect() as connection:
        row = connection.execute("""
            SELECT 1 FROM public.stylist_access
            WHERE telegram_user_id = %s
        """, (telegram_user_id,)).fetchone()
    return row is not None


def validate_succeeded_payment(
    payment: dict[str, Any],
    *,
    order_id: str,
    telegram_user_id: int,
) -> None:
    """Raise if an API-fetched payment does not exactly match the pending order."""
    if payment.get("status") != "succeeded" or payment.get("paid") is not True:
        raise PaymentValidationError("Payment is not successfully paid")
    amount = payment.get("amount") or {}
    try:
        actual_amount = Decimal(str(amount.get("value", ""))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise PaymentValidationError("Invalid payment amount") from None
    if actual_amount != PAYMENT_AMOUNT or amount.get("currency") != PAYMENT_CURRENCY:
        raise PaymentValidationError("Payment amount or currency mismatch")
    metadata = payment.get("metadata") or {}
    if str(metadata.get("order_id", "")) != order_id:
        raise PaymentValidationError("Payment order metadata mismatch")
    try:
        metadata_user_id = int(metadata.get("telegram_user_id"))
    except (TypeError, ValueError):
        raise PaymentValidationError("Payment user metadata is invalid") from None
    if metadata_user_id != telegram_user_id:
        raise PaymentValidationError("Payment user metadata mismatch")


async def create_yookassa_payment(order_id: str, telegram_user_id: int, service_type: str = "stylist") -> dict[str, Any]:
    import aiohttp

    shop_id = os.getenv("YOOKASSA_SHOP_ID")
    secret_key = os.getenv("YOOKASSA_SECRET_KEY")
    return_url = os.getenv("YOOKASSA_RETURN_URL")
    if not shop_id or not secret_key or not return_url:
        raise PaymentConfigurationError(
            "YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY and YOOKASSA_RETURN_URL must be configured"
        )

    if service_type not in {"stylist", "care"}:
        raise ValueError("Unsupported YooKassa service type")
    amount_value = "99.00" if service_type == "care" else "49.00"
    description = (
        "Консультационная услуга по подбору ухода"
        if service_type == "care"
        else "Персональный AI-гардероб"
    )
    payload = {
        "amount": {"value": amount_value, "currency": PAYMENT_CURRENCY},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description,
        "metadata": {
            "service_type": service_type,
            "order_id": order_id,
            "telegram_user_id": str(telegram_user_id),
        },
    }
    timeout = aiohttp.ClientTimeout(total=20)
    auth = aiohttp.BasicAuth(shop_id, secret_key)
    async with aiohttp.ClientSession(timeout=timeout, auth=auth) as session:
        async with session.post(
            f"{YOOKASSA_API_URL}/payments",
            json=payload,
            headers={"Idempotence-Key": order_id},
        ) as response:
            body = await response.json(content_type=None)
            if response.status not in (200, 201):
                raise RuntimeError(f"YooKassa create payment failed: HTTP {response.status}")
    confirmation_url = (body.get("confirmation") or {}).get("confirmation_url")
    payment_id = body.get("id")
    if not payment_id or not confirmation_url:
        raise RuntimeError("YooKassa response has no payment id or confirmation URL")
    return {"id": payment_id, "confirmation_url": confirmation_url}


async def fetch_yookassa_payment(payment_id: str) -> dict[str, Any]:
    import aiohttp

    shop_id = os.getenv("YOOKASSA_SHOP_ID")
    secret_key = os.getenv("YOOKASSA_SECRET_KEY")
    if not shop_id or not secret_key:
        raise PaymentConfigurationError("YooKassa credentials are not configured")
    timeout = aiohttp.ClientTimeout(total=15)
    auth = aiohttp.BasicAuth(shop_id, secret_key)
    async with aiohttp.ClientSession(timeout=timeout, auth=auth) as session:
        async with session.get(f"{YOOKASSA_API_URL}/payments/{payment_id}") as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                raise RuntimeError(f"YooKassa payment lookup failed: HTTP {response.status}")
            return body


def grant_access_from_payment_sync(payment: dict[str, Any]) -> tuple[int, bool]:
    metadata = payment.get("metadata") or {}
    order_id = str(metadata.get("order_id", ""))
    try:
        telegram_user_id = int(metadata.get("telegram_user_id"))
    except (TypeError, ValueError):
        raise PaymentValidationError("Missing Telegram user id in payment metadata") from None
    if not order_id or not payment.get("id"):
        raise PaymentValidationError("Missing order or payment id")

    with _db_connect() as connection:
        order = connection.execute("""
            SELECT telegram_user_id, amount, currency, status, payment_id
            FROM public.stylist_payment_orders
            WHERE order_id = %s::uuid
            FOR UPDATE
        """, (order_id,)).fetchone()
        if order is None:
            raise PaymentValidationError("Payment order was not found")
        order_user_id, order_amount, order_currency, order_status, stored_payment_id = order
        if order_status not in {"pending", "succeeded"}:
            raise PaymentValidationError("Payment order is not payable")
        if int(order_user_id) != telegram_user_id:
            raise PaymentValidationError("Order belongs to another Telegram user")
        if Decimal(str(order_amount)).quantize(Decimal("0.01")) != PAYMENT_AMOUNT:
            raise PaymentValidationError("Stored order amount mismatch")
        if order_currency != PAYMENT_CURRENCY:
            raise PaymentValidationError("Stored order currency mismatch")
        if stored_payment_id and stored_payment_id != payment["id"]:
            raise PaymentValidationError("Payment id does not match the order")
        validate_succeeded_payment(
            payment,
            order_id=order_id,
            telegram_user_id=telegram_user_id,
        )
        connection.execute("""
            UPDATE public.stylist_payment_orders
            SET payment_id = COALESCE(payment_id, %s),
                status = 'succeeded',
                paid_at = COALESCE(paid_at, now())
            WHERE order_id = %s::uuid
        """, (payment["id"], order_id))
        inserted = connection.execute("""
            INSERT INTO public.stylist_access (telegram_user_id, payment_id)
            VALUES (%s, %s)
            ON CONFLICT (telegram_user_id) DO NOTHING
        """, (telegram_user_id, payment["id"]))
        return telegram_user_id, inserted.rowcount == 1



CARE_PAYMENT_AMOUNT = Decimal("99.00")


def create_care_pending_order_sync(telegram_user_id: int) -> str:
    """Return the user's existing pending care order or create exactly one."""
    import uuid

    with _db_connect() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (int(telegram_user_id),))
        row = connection.execute("""
            SELECT order_id FROM public.care_orders
            WHERE telegram_user_id = %s AND status = 'pending'
            ORDER BY created_at DESC LIMIT 1
        """, (telegram_user_id,)).fetchone()
        if row:
            return str(row[0])
        order_id = str(uuid.uuid4())
        connection.execute("""
            INSERT INTO public.care_orders
                (order_id, telegram_user_id, amount, currency, status)
            VALUES (%s::uuid, %s, %s, 'RUB', 'pending')
        """, (order_id, telegram_user_id, CARE_PAYMENT_AMOUNT))
    return order_id


def save_care_payment_id_sync(order_id: str, payment_id: str) -> None:
    with _db_connect() as connection:
        connection.execute("""
            UPDATE public.care_orders
            SET payment_id = COALESCE(payment_id, %s)
            WHERE order_id = %s::uuid AND status = 'pending'
              AND (payment_id IS NULL OR payment_id = %s)
        """, (payment_id, order_id, payment_id))


def has_care_access_sync(telegram_user_id: int) -> bool:
    with _db_connect() as connection:
        row = connection.execute("""
            SELECT 1 FROM public.care_access WHERE telegram_user_id = %s
        """, (telegram_user_id,)).fetchone()
    return row is not None


def get_care_access_order_sync(telegram_user_id: int) -> str | None:
    with _db_connect() as connection:
        row = connection.execute("""
            SELECT order_id FROM public.care_access WHERE telegram_user_id = %s
        """, (telegram_user_id,)).fetchone()
    return str(row[0]) if row else None


def grant_care_access_from_payment_sync(payment: dict[str, Any]) -> tuple[int, bool, str]:
    """Validate a fetched YooKassa payment and atomically grant care access."""
    metadata = payment.get("metadata") or {}
    if metadata.get("service_type") != "care":
        raise PaymentValidationError("Payment is not a care order")
    order_id = str(metadata.get("order_id", ""))
    try:
        telegram_user_id = int(metadata.get("telegram_user_id"))
        actual_amount = Decimal(str((payment.get("amount") or {}).get("value", ""))).quantize(Decimal("0.01"))
    except (TypeError, ValueError, InvalidOperation):
        raise PaymentValidationError("Invalid care payment metadata or amount") from None
    amount = payment.get("amount") or {}
    if payment.get("status") != "succeeded" or payment.get("paid") is not True:
        raise PaymentValidationError("Care payment is not succeeded")
    if actual_amount != CARE_PAYMENT_AMOUNT or amount.get("currency") != "RUB":
        raise PaymentValidationError("Care payment amount or currency mismatch")
    if not order_id or not payment.get("id"):
        raise PaymentValidationError("Missing care order or payment id")

    with _db_connect() as connection:
        order = connection.execute("""
            SELECT telegram_user_id, amount, currency, status, payment_id
            FROM public.care_orders WHERE order_id = %s::uuid FOR UPDATE
        """, (order_id,)).fetchone()
        if order is None:
            raise PaymentValidationError("Care order was not found")
        owner, stored_amount, currency, status, stored_payment_id = order
        if int(owner) != telegram_user_id:
            raise PaymentValidationError("Care order belongs to another user")
        if Decimal(str(stored_amount)).quantize(Decimal("0.01")) != CARE_PAYMENT_AMOUNT or currency != "RUB":
            raise PaymentValidationError("Stored care order amount mismatch")
        if status not in {"pending", "succeeded"}:
            raise PaymentValidationError("Care order is not payable")
        if stored_payment_id and stored_payment_id != payment["id"]:
            raise PaymentValidationError("Care payment id mismatch")
        connection.execute("""
            UPDATE public.care_orders
            SET payment_id = COALESCE(payment_id, %s), status = 'succeeded',
                paid_at = COALESCE(paid_at, now())
            WHERE order_id = %s::uuid
        """, (payment["id"], order_id))
        inserted = connection.execute("""
            INSERT INTO public.care_access (telegram_user_id, order_id)
            VALUES (%s, %s::uuid)
            ON CONFLICT (telegram_user_id) DO NOTHING
        """, (telegram_user_id, order_id))
        return telegram_user_id, inserted.rowcount == 1, order_id


def set_care_order_mode_sync(order_id: str, telegram_user_id: int, mode: str) -> bool:
    if mode not in {"photo", "quiz"}:
        return False
    with _db_connect() as connection:
        row = connection.execute("""
            UPDATE public.care_orders
            SET mode = %s
            WHERE order_id = %s::uuid AND telegram_user_id = %s AND status = 'succeeded'
            RETURNING order_id
        """, (mode, order_id, telegram_user_id)).fetchone()
    return row is not None


def record_care_photo_consent_sync(order_id: str, telegram_user_id: int) -> bool:
    with _db_connect() as connection:
        row = connection.execute("""
            UPDATE public.care_orders SET photo_consent_at = now()
            WHERE order_id = %s::uuid AND telegram_user_id = %s AND status = 'succeeded'
            RETURNING order_id
        """, (order_id, telegram_user_id)).fetchone()
    return row is not None


def update_care_order_answers_sync(order_id: str, telegram_user_id: int, answers: dict[str, str]) -> bool:
    import json

    with _db_connect() as connection:
        row = connection.execute("""
            UPDATE public.care_orders
            SET answers = answers || %s::jsonb
            WHERE order_id = %s::uuid AND telegram_user_id = %s AND status = 'succeeded'
            RETURNING order_id
        """, (json.dumps(answers, ensure_ascii=False), order_id, telegram_user_id)).fetchone()
    return row is not None


def get_care_order_sync(order_id: str, telegram_user_id: int) -> dict[str, Any] | None:
    with _db_connect() as connection:
        row = connection.execute("""
            SELECT mode, answers, result_text, result_status, status, photo_consent_at
            FROM public.care_orders
            WHERE order_id = %s::uuid AND telegram_user_id = %s
        """, (order_id, telegram_user_id)).fetchone()
    if not row:
        return None
    return {
        "mode": row[0],
        "answers": row[1] or {},
        "result_text": row[2],
        "result_status": row[3],
        "status": row[4],
        "photo_consent_at": row[5],
    }


def save_care_result_sync(order_id: str, telegram_user_id: int, result: str) -> None:
    with _db_connect() as connection:
        connection.execute("""
            UPDATE public.care_orders
            SET result_text = %s, result_status = 'completed'
            WHERE order_id = %s::uuid AND telegram_user_id = %s AND status = 'succeeded'
        """, (result, order_id, telegram_user_id))


def mark_care_result_status_sync(order_id: str, telegram_user_id: int, status: str) -> None:
    if status not in {"pending", "processing", "failed", "completed"}:
        raise ValueError("Invalid care result status")
    with _db_connect() as connection:
        connection.execute("""
            UPDATE public.care_orders SET result_status = %s
            WHERE order_id = %s::uuid AND telegram_user_id = %s AND status = 'succeeded'
        """, (status, order_id, telegram_user_id))
