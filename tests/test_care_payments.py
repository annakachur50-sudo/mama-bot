from decimal import Decimal

import pytest

from payments import (
    PaymentValidationError,
    validate_care_payment,
)


def valid_payment():
    return {
        "id": "pay_care_123",
        "status": "succeeded",
        "paid": True,
        "amount": {"value": "99.00", "currency": "RUB"},
        "metadata": {
            "service_type": "care",
            "order_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
            "telegram_user_id": "123456",
        },
    }


def test_valid_care_payment_is_accepted():
    validate_care_payment(
        valid_payment(),
        order_id="d290f1ee-6c54-4b01-90e6-d701748f0851",
        telegram_user_id=123456,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(status="pending"),
        lambda p: p.update(paid=False),
        lambda p: p.update(amount={"value": "49.00", "currency": "RUB"}),
        lambda p: p.update(amount={"value": "99.00", "currency": "USD"}),
        lambda p: p["metadata"].update(service_type="stylist"),
        lambda p: p["metadata"].update(order_id="another-order"),
        lambda p: p["metadata"].update(telegram_user_id="654321"),
        lambda p: p.pop("id"),
    ],
)
def test_invalid_care_payment_is_rejected(mutate):
    payment = valid_payment()
    mutate(payment)
    with pytest.raises(PaymentValidationError):
        validate_care_payment(
            payment,
            order_id="d290f1ee-6c54-4b01-90e6-d701748f0851",
            telegram_user_id=123456,
        )
