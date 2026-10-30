import unittest
from decimal import Decimal

from payments import (
    PAYMENT_AMOUNT,
    PAYMENT_CURRENCY,
    PaymentValidationError,
    validate_succeeded_payment,
)


def valid_payment():
    return {
        "id": "pay_test_123",
        "status": "succeeded",
        "paid": True,
        "amount": {"value": "49.00", "currency": "RUB"},
        "metadata": {"order_id": "order-1", "telegram_user_id": "123456"},
    }


class YooKassaPaymentValidationTests(unittest.TestCase):
    def test_accepts_exact_successful_payment(self):
        validate_succeeded_payment(
            valid_payment(), order_id="order-1", telegram_user_id=123456
        )

    def test_rejects_pending_payment(self):
        payment = valid_payment()
        payment["status"] = "pending"
        with self.assertRaises(PaymentValidationError):
            validate_succeeded_payment(
                payment, order_id="order-1", telegram_user_id=123456
            )

    def test_rejects_wrong_amount(self):
        payment = valid_payment()
        payment["amount"]["value"] = "4900.00"
        with self.assertRaises(PaymentValidationError):
            validate_succeeded_payment(
                payment, order_id="order-1", telegram_user_id=123456
            )

    def test_rejects_wrong_currency(self):
        payment = valid_payment()
        payment["amount"]["currency"] = "XTR"
        with self.assertRaises(PaymentValidationError):
            validate_succeeded_payment(
                payment, order_id="order-1", telegram_user_id=123456
            )

    def test_rejects_wrong_user(self):
        with self.assertRaises(PaymentValidationError):
            validate_succeeded_payment(
                valid_payment(), order_id="order-1", telegram_user_id=999
            )

    def test_rejects_wrong_order(self):
        with self.assertRaises(PaymentValidationError):
            validate_succeeded_payment(
                valid_payment(), order_id="another-order", telegram_user_id=123456
            )

    def test_rejects_unpaid_flag(self):
        payment = valid_payment()
        payment["paid"] = False
        with self.assertRaises(PaymentValidationError):
            validate_succeeded_payment(
                payment, order_id="order-1", telegram_user_id=123456
            )


if __name__ == "__main__":
    unittest.main()
