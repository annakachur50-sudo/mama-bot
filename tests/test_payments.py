import os
import sqlite3
import tempfile
import unittest

from aiogram import Dispatcher
from aiogram.types import LabeledPrice, PreCheckoutQuery

from payments import (
    PAYMENT_AMOUNT,
    PAYMENT_CURRENCY,
    build_invoice_parameters,
    create_pending_order,
    find_order_by_payload,
    has_wardrobe_access,
    record_successful_payment,
    validate_pre_checkout,
)


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.NamedTemporaryFile(delete=False)
        self.temp.close()
        self.connection = sqlite3.connect(self.temp.name)
        self.connection.row_factory = sqlite3.Row
        self.factory = lambda: self.connection

    def tearDown(self):
        self.connection.close()
        os.unlink(self.temp.name)

    def test_invoice_amount_is_4900(self):
        invoice = build_invoice_parameters("test-provider-token", "wardrobe:test")
        self.assertEqual(invoice["prices"][0].amount, 4900)

    def test_invoice_currency_is_rub(self):
        invoice = build_invoice_parameters("test-provider-token", "wardrobe:test")
        self.assertEqual(invoice["currency"], "RUB")

    def test_invoice_uses_provider_token(self):
        invoice = build_invoice_parameters("test-provider-token", "wardrobe:test")
        self.assertEqual(invoice["provider_token"], "test-provider-token")

    def test_missing_token_disables_invoice(self):
        self.assertIsNone(build_invoice_parameters(None, "wardrobe:test"))

    def test_aiogram_v3_payment_types_and_dispatcher_hook_are_available(self):
        self.assertTrue(hasattr(Dispatcher, "pre_checkout_query"))
        self.assertTrue(LabeledPrice)
        self.assertTrue(PreCheckoutQuery)

    def test_repeated_checkout_reuses_pending_order(self):
        first = create_pending_order(7, self.factory)
        second = create_pending_order(7, self.factory)
        self.assertEqual(first["order_id"], second["order_id"])
        self.assertEqual(first["payload"], second["payload"])

    def test_valid_pre_checkout_is_accepted(self):
        order = {"telegram_user_id": 7, "amount": 4900, "currency": "RUB",
                 "status": "pending", "telegram_payment_charge_id": None}
        self.assertEqual(validate_pre_checkout(order, 7, 4900, "RUB"), (True, ""))

    def test_wrong_amount_or_currency_is_rejected(self):
        order = {"telegram_user_id": 7, "amount": 4900, "currency": "RUB",
                 "status": "pending", "telegram_payment_charge_id": None}
        self.assertFalse(validate_pre_checkout(order, 7, 100, "RUB")[0])
        self.assertFalse(validate_pre_checkout(order, 7, 4900, "EUR")[0])

    def test_unknown_payload_is_rejected(self):
        self.assertFalse(validate_pre_checkout(None, 7, 4900, "RUB")[0])

    def test_other_user_cannot_pay_order(self):
        order = {"telegram_user_id": 7, "amount": 4900, "currency": "RUB",
                 "status": "pending", "telegram_payment_charge_id": None}
        self.assertFalse(validate_pre_checkout(order, 8, 4900, "RUB")[0])

    def test_successful_payment_marks_order_paid_and_grants_access(self):
        order = create_pending_order(7, self.factory)
        granted = record_successful_payment(
            order["payload"], 7, 4900, "RUB", "telegram-charge-1", "provider-charge-1",
            self.factory,
        )
        self.assertTrue(granted)
        saved = find_order_by_payload(order["payload"], self.factory)
        self.assertEqual(saved["status"], "paid")
        self.assertEqual(saved["telegram_payment_charge_id"], "telegram-charge-1")
        self.assertEqual(saved["provider_payment_charge_id"], "provider-charge-1")
        self.assertTrue(has_wardrobe_access(7, self.factory))

    def test_duplicate_successful_payment_does_not_grant_again(self):
        order = create_pending_order(7, self.factory)
        self.assertTrue(record_successful_payment(
            order["payload"], 7, 4900, "RUB", "telegram-charge-1", "provider-charge-1",
            self.factory,
        ))
        self.assertFalse(record_successful_payment(
            order["payload"], 7, 4900, "RUB", "telegram-charge-1", "provider-charge-1",
            self.factory,
        ))
        count = self.connection.execute(
            "SELECT COUNT(*) FROM wardrobe_access WHERE telegram_user_id = 7"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_unpaid_user_has_no_access(self):
        create_pending_order(7, self.factory)
        self.assertFalse(has_wardrobe_access(7, self.factory))

    def test_access_survives_reopening_database(self):
        order = create_pending_order(7, self.factory)
        self.assertTrue(record_successful_payment(
            order["payload"], 7, PAYMENT_AMOUNT, PAYMENT_CURRENCY,
            "telegram-charge-1", "provider-charge-1", self.factory,
        ))
        self.connection.commit()
        self.connection.close()
        self.connection = sqlite3.connect(self.temp.name)
        self.connection.row_factory = sqlite3.Row
        self.factory = lambda: self.connection
        self.assertTrue(has_wardrobe_access(7, self.factory))


if __name__ == "__main__":
    unittest.main()
