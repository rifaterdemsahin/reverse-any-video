"""Accounts, sign-in links, sessions, credit and Stripe signature checks. No network, in-memory store."""
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["SESSION_SECRET"] = "test-session-secret"

import accounts  # noqa: E402
import payments  # noqa: E402


class MemStore:
    def __init__(self):
        self.docs = {}

    def put_json(self, name, obj):
        self.docs[name] = json.loads(json.dumps(obj))

    def get_json(self, name):
        d = self.docs.get(name)
        return json.loads(json.dumps(d)) if d is not None else None


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.acc = accounts.Accounts(MemStore())

    def test_email_is_checked_and_lowercased(self):
        self.assertEqual(accounts.normalise("  Info@Pexabo.com "), "info@pexabo.com")
        with self.assertRaises(accounts.AccountError):
            accounts.normalise("not-an-email")

    def test_credit_is_added_once_per_reference(self):
        self.acc.credit("a@b.co", 2000, "cs_1")
        self.acc.credit("a@b.co", 2000, "cs_1")          # a repeated webhook
        self.assertEqual(self.acc.get("a@b.co")["balance_cents"], 2000)
        self.assertEqual(len(self.acc.get("a@b.co")["ledger"]), 1)

    def test_debit_needs_enough_credit(self):
        self.acc.credit("a@b.co", 500, "cs_2")
        self.acc.debit("a@b.co", 300, "job_1")
        self.assertEqual(self.acc.get("a@b.co")["balance_cents"], 200)
        with self.assertRaises(accounts.AccountError):
            self.acc.debit("a@b.co", 300, "job_2")

    def test_sign_in_link_works_once(self):
        token = self.acc.start_login("a@b.co")
        self.assertEqual(self.acc.finish_login(token), "a@b.co")
        with self.assertRaises(accounts.AccountError):
            self.acc.finish_login(token)

    def test_sign_in_link_only_stores_a_hash(self):
        token = self.acc.start_login("a@b.co")
        self.assertNotIn(token, json.dumps(self.acc.store.docs))

    def test_session_round_trip_and_tamper_check(self):
        value = self.acc.session_value("a@b.co")
        self.assertEqual(self.acc.email_from_session(value), "a@b.co")
        self.assertIsNone(self.acc.email_from_session(value[:-4] + "AAAA"))
        self.assertIsNone(self.acc.email_from_session(None))

    def test_expired_session_is_refused(self):
        real = time.time
        try:
            value = self.acc.session_value("a@b.co")
            time.time = lambda: real() + accounts.SESSION_TTL + 10
            self.assertIsNone(self.acc.email_from_session(value))
        finally:
            time.time = real


class StripeTests(unittest.TestCase):
    SECRET = "whsec_test"

    def sign(self, body: bytes, ts: int) -> str:
        sig = hmac.new(self.SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"

    def test_valid_signature_passes(self):
        body = b'{"id":"evt_1"}'
        now = 1_700_000_000
        self.assertTrue(payments.verify_signature(body, self.sign(body, now), self.SECRET, now=now))

    def test_wrong_secret_or_body_fails(self):
        body = b'{"id":"evt_1"}'
        now = 1_700_000_000
        header = self.sign(body, now)
        self.assertFalse(payments.verify_signature(body, header, "whsec_other", now=now))
        self.assertFalse(payments.verify_signature(b'{"id":"evt_2"}', header, self.SECRET, now=now))

    def test_old_timestamp_fails(self):
        body = b"{}"
        self.assertFalse(payments.verify_signature(body, self.sign(body, 1_000), self.SECRET, now=1_000 + 999))

    def test_paid_checkout_gives_the_credit(self):
        event = {"id": "evt_9", "type": "checkout.session.completed", "data": {"object": {
            "id": "cs_9", "payment_status": "paid",
            "metadata": {"email": "Buyer@Example.com", "pack": "Creator", "credit_cents": "2000"}}}}
        paid = payments.paid_event(event)
        self.assertEqual(paid, {"email": "buyer@example.com", "cents": 2000, "ref": "cs_9", "pack": "Creator"})

    def test_unpaid_or_other_events_give_nothing(self):
        self.assertIsNone(payments.paid_event({"type": "payment_intent.created", "data": {"object": {}}}))
        unpaid = {"type": "checkout.session.completed", "data": {"object": {"payment_status": "unpaid", "metadata": {"email": "a@b.co", "credit_cents": "500"}}}}
        self.assertIsNone(payments.paid_event(unpaid))

    def test_live_key_refused_without_opt_in(self):
        os.environ.pop("STRIPE_ALLOW_LIVE", None)
        with self.assertRaises(payments.StripeError):
            payments.check_mode("sk_live_abc")
        self.assertEqual(payments.check_mode("sk_test_abc"), "test")


if __name__ == "__main__":
    unittest.main()
