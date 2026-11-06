import unittest
from decimal import Decimal
from unittest.mock import patch

from payments import grant_care_access_from_payment_sync


class FakeResult:
    def __init__(self, row=None, rowcount=1):
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, *, access_inserted=True):
        self.access_inserted = access_inserted
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if "SELECT telegram_user_id, amount, currency, status, payment_id" in query:
            return FakeResult((123456, Decimal("99.00"), "RUB", "pending", None))
        if "INSERT INTO public.care_access" in query:
            return FakeResult(rowcount=1 if self.access_inserted else 0)
        return FakeResult(rowcount=1)


def succeeded_payment():
    return {
        "id": "care-payment-1",
        "status": "succeeded",
        "paid": True,
        "amount": {"value": "99.00", "currency": "RUB"},
        "metadata": {
            "service_type": "care",
            "order_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
            "telegram_user_id": "123456",
        },
    }


class CareAccessGrantTests(unittest.TestCase):
    def test_access_is_granted_once(self):
        connection = FakeConnection(access_inserted=True)
        with patch("payments._db_connect", return_value=connection):
            result = grant_care_access_from_payment_sync(succeeded_payment())
        self.assertEqual(
            result,
            (123456, True, "d290f1ee-6c54-4b01-90e6-d701748f0851"),
        )

    def test_duplicate_notification_does_not_grant_access_twice(self):
        connection = FakeConnection(access_inserted=False)
        with patch("payments._db_connect", return_value=connection):
            result = grant_care_access_from_payment_sync(succeeded_payment())
        self.assertEqual(
            result,
            (123456, False, "d290f1ee-6c54-4b01-90e6-d701748f0851"),
        )


if __name__ == "__main__":
    unittest.main()
