"""Offline contract/error tests; never make real PayPal requests."""

import contextlib
import io
import json
import os
import unittest
from unittest.mock import Mock, patch

import requests

from paypal_client import PayPalClient, PayPalError


def response(status, body=None, *, raw=None, debug_id=None):
    result = requests.Response()
    result.status_code = status
    result._content = (raw if raw is not None else json.dumps(body)).encode()
    if debug_id:
        result.headers["PayPal-Debug-Id"] = debug_id
    return result


class PayPalClientTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "PAYPAL_CLIENT_ID": "test-client", "PAYPAL_SECRET": "test-secret",
            "PAYPAL_ENVIRONMENT": "sandbox",
            "PAYPAL_RETURN_URL": "http://127.0.0.1:8000/paypal/return",
            "PAYPAL_CANCEL_URL": "http://127.0.0.1:8000/paypal/cancel",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = PayPalClient()
        self.addCleanup(self.client.close)
        self.http = Mock()
        self.client._session.request = self.http
        self.token = response(200, {"access_token": "token", "expires_in": 3600})

    def test_authorize_partial_final_capture_and_void(self):
        self.http.side_effect = [
            self.token,
            response(201, {"id": "ORDER1", "links": [
                {"rel": "approve", "href": "https://www.sandbox.paypal.com/approve"}]}),
            response(201, {"purchase_units": [{"payments": {"authorizations": [
                {"id": "AUTH1", "status": "CREATED"}]}}]}),
            response(201, {"id": "CAPTURE1", "status": "COMPLETED"}),
            response(204, raw=""),
        ]
        order_id, url = self.client.create_session_hold(20.00)
        self.assertEqual(order_id, "ORDER1")
        self.assertTrue(url.startswith("https://"))
        auth_id = self.client.authorize_order(order_id)
        capture = self.client.capture_session_funds(auth_id, 3.50)
        self.assertEqual(capture["status"], "COMPLETED")
        # Separate unused authorization, not the captured authorization.
        self.assertIsNone(self.client.void_session("UNUSEDAUTH"))
        calls = self.http.call_args_list
        self.assertEqual(len(calls), 5)  # Only one token fetch across operations.
        self.assertEqual(calls[0].kwargs["auth"], ("test-client", "test-secret"))
        self.assertEqual(calls[0].kwargs["data"], {"grant_type": "client_credentials"})
        self.assertEqual(calls[1].kwargs["json"]["intent"], "AUTHORIZE")
        self.assertEqual(calls[1].kwargs["json"]["purchase_units"][0]["amount"]["value"], "20.00")
        payload=calls[1].kwargs['json']
        self.assertNotIn('application_context',payload)
        experience=payload['payment_source']['paypal']['experience_context']
        self.assertEqual(experience['user_action'],'PAY_NOW')
        self.assertEqual(experience['return_url'],'http://127.0.0.1:8000/paypal/return')
        self.assertEqual(experience['cancel_url'],'http://127.0.0.1:8000/paypal/cancel')
        self.assertTrue(calls[2].args[1].endswith("/ORDER1/authorize"))
        self.assertTrue(calls[3].args[1].endswith("/AUTH1/capture"))
        self.assertEqual(calls[3].kwargs["json"], {
            "amount": {"currency_code": "USD", "value": "3.50"}, "final_capture": True})
        self.assertTrue(calls[4].args[1].endswith("/UNUSEDAUTH/void"))
        for call in calls[1:]:
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer token")
            self.assertIn("PayPal-Request-Id", call.kwargs["headers"])
            self.assertEqual(call.kwargs["timeout"], (10, 30))

    def test_http_errors_print_raw_diagnostics_without_retry(self):
        for status in (400, 401, 403, 404, 409, 422, 429, 500, 503):
            with self.subTest(status=status):
                self.http.reset_mock()
                self.http.side_effect = [self.token, response(status, {
                    "message": "Exact PayPal error", "debug_id": "body-debug",
                    "details": [{"issue": "TEST_ISSUE"}],
                }, debug_id="raw-debug-123")]
                self.client._access_token = None
                with contextlib.redirect_stderr(io.StringIO()) as output:
                    with self.assertRaises(PayPalError) as caught:
                        self.client.capture_session_funds("AUTH1", 3.50, request_id="stable-id")
                self.assertEqual(caught.exception.status_code, status)
                self.assertEqual(caught.exception.debug_id, "raw-debug-123")
                self.assertEqual(caught.exception.request_id, "stable-id")
                self.assertIn("Exact PayPal error", output.getvalue())
                self.assertIn("raw-debug-123", output.getvalue())
                self.assertIn("TEST_ISSUE", output.getvalue())
                self.assertEqual(self.http.call_count, 2)

    def test_body_debug_id_and_oauth_failure(self):
        self.http.return_value = response(401, {
            "error": "invalid_client", "debug_id": "body-only-debug"})
        with contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(PayPalError) as caught:
                self.client.get_access_token()
        self.assertEqual(caught.exception.debug_id, "body-only-debug")
        self.assertIn("invalid_client", output.getvalue())

    def test_non_json_http_error_and_invalid_success_json(self):
        for status in (502, 200):
            with self.subTest(status=status):
                self.http.return_value = response(status, raw="<html>upstream failure</html>")
                with contextlib.redirect_stderr(io.StringIO()) as output:
                    with self.assertRaises(PayPalError):
                        self.client.get_access_token()
                self.assertIn("<html>upstream failure</html>", output.getvalue())

    def test_transport_failure_preserves_id_without_retry(self):
        self.http.side_effect = [self.token, requests.Timeout("read timed out")]
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(PayPalError) as caught:
                self.client.capture_session_funds("AUTH1", 3.50, request_id="retry-id")
        self.assertEqual(caught.exception.request_id, "retry-id")
        self.assertEqual(self.http.call_count, 2)

    def test_invalid_amounts_and_ids_never_contact_paypal(self):
        for amount in (0, -1, float("nan"), float("inf"), 0.001, True, "invalid"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.client.create_session_hold(amount)
        for resource_id in ("", "../bad", "AUTH1/capture", None):
            with self.subTest(resource_id=resource_id), self.assertRaises(ValueError):
                self.client.void_session(resource_id)
        self.http.assert_not_called()

    def test_expired_token_is_refreshed(self):
        self.http.return_value = self.token
        self.assertEqual(self.client.get_access_token(), "token")
        self.assertEqual(self.client.get_access_token(), "token")
        self.assertEqual(self.http.call_count, 1)
        self.client._token_expires_at = 0
        self.client.get_access_token()
        self.assertEqual(self.http.call_count, 2)

    def test_environment_validation(self):
        with patch.dict(os.environ, {"PAYPAL_ENVIRONMENT": "unknown"}):
            with self.assertRaises(ValueError):
                PayPalClient()
        with patch.dict(os.environ, {"PAYPAL_SECRET": ""}):
            with self.assertRaises(ValueError):
                PayPalClient()
        with patch.dict(os.environ, {"PAYPAL_ENVIRONMENT": "live"}):
            with self.assertRaises(ValueError):
                PayPalClient()

    def test_modern_payer_action_link(self):
        self.http.side_effect=[self.token,response(201,{'id':'ORDER1','links':[{'rel':'payer-action','href':'https://www.sandbox.paypal.com/checkoutnow?token=ORDER1'}]})]
        oid,url=self.client.create_session_hold(20.00)
        self.assertEqual(oid,'ORDER1')
        self.assertIn('token=ORDER1',url)

    def test_return_urls_must_point_to_local_workspace(self):
        for value in ('https://example.com/return','javascript:alert(1)','http://localhost:8000/paypal/return?approved=true','http://user:pass@localhost/return'):
            with self.subTest(value=value),patch.dict(os.environ,{'PAYPAL_RETURN_URL':value}):
                with self.assertRaises(ValueError): PayPalClient()


if __name__ == "__main__":
    unittest.main()
