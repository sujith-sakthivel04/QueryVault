"""Standalone PayPal Orders v2 / Payments v2 client (Python 3.10+)."""

from __future__ import annotations

import os
import re
import sys
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv


class PayPalError(RuntimeError):
    """API/transport failure, including diagnostic data for reconciliation.

    A timeout or 5xx can occur after PayPal has processed a payment. Inspect
    PayPal before retrying, and reuse request_id for the same logical operation.
    """

    def __init__(self, message: str, *, status_code: int | None = None,
                 debug_id: str | None = None, response_body: str | None = None,
                 request_id: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.debug_id = debug_id
        self.response_body = response_body
        self.request_id = request_id


class PayPalClient:
    """Load credentials from environment or the .env next to this module.

    PAYPAL_ENVIRONMENT must be sandbox. Environment variables
    take precedence over .env. Instances are intended for sequential use.
    """

    BASE_URLS = {
        "sandbox": "https://api-m.sandbox.paypal.com",
        "live": "https://api-m.paypal.com",
    }

    def __init__(self) -> None:
        if os.getenv('QUERYVAULT_MODE', 'local') != 'local':
            raise ValueError('PayPal is disabled outside the local operator workflow.')
        load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)
        self.client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
        self.secret = os.getenv("PAYPAL_SECRET", "").strip()
        self.environment = os.getenv("PAYPAL_ENVIRONMENT", "sandbox").strip().lower()
        if not self.client_id or not self.secret:
            raise ValueError("Set PAYPAL_CLIENT_ID and PAYPAL_SECRET in .env or the environment.")
        if self.environment not in self.BASE_URLS:
            raise ValueError("PAYPAL_ENVIRONMENT must be 'sandbox' or 'live'.")
        if self.environment != "sandbox":
            raise ValueError("QueryVault permits PayPal sandbox only.")
        self.base_url = self.BASE_URLS[self.environment]
        self.return_url = os.getenv("PAYPAL_RETURN_URL", "http://127.0.0.1:8000/paypal/return")
        self.cancel_url = os.getenv("PAYPAL_CANCEL_URL", "http://127.0.0.1:8000/paypal/cancel")
        for url in (self.return_url, self.cancel_url):
            parsed = urlsplit(url)
            if (parsed.scheme not in ("http", "https")
                    or parsed.hostname not in ("127.0.0.1", "localhost")
                    or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise ValueError("Sandbox checkout URLs must be local HTTP(S) URLs without credentials, query, or fragment.")
        self.timeout = (10, 30)  # Connect and read timeouts, in seconds.
        self._session = requests.Session()
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    def close(self) -> None:
        """Release pooled HTTP connections."""
        self._session.close()

    def __enter__(self) -> PayPalClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @staticmethod
    def _amount(amount_usd: float) -> dict[str, str]:
        try:
            if isinstance(amount_usd, bool):
                raise ValueError
            value = Decimal(str(amount_usd))
            if not value.is_finite() or value <= 0:
                raise ValueError
            rounded = value.quantize(Decimal("0.01"))
            if rounded != value:
                raise ValueError
            return {"currency_code": "USD", "value": format(rounded, ".2f")}
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("amount_usd must be positive, finite, and have at most two decimal places.") from exc

    @staticmethod
    def _resource_id(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9]+", value):
            raise ValueError("PayPal resource IDs must be nonempty alphanumeric strings.")
        return value

    @staticmethod
    def _fail(response: requests.Response, message: str,
              request_id: str | None) -> None:
        try:
            body = response.json()
        except ValueError:
            body = {}
        debug_id = response.headers.get("PayPal-Debug-Id")
        if not debug_id and isinstance(body, dict):
            debug_id = body.get("debug_id")
        # Preserve PayPal's exact response, including nested issue descriptions.
        print(f"{message}\nPayPal debug ID: {debug_id or '(not supplied)'}"
              f"\nPayPal request ID: {request_id or '(not supplied)'}"
              f"\nRaw PayPal response: {response.text}", file=sys.stderr)
        raise PayPalError(message, status_code=response.status_code,
                          debug_id=debug_id, response_body=response.text,
                          request_id=request_id)

    def _request(self, path: str, *, oauth: bool = False,
                 payload: dict[str, Any] | None = None,
                 request_id: str | None = None, method: str = "POST") -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        kwargs: dict[str, Any] = {}
        if oauth:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            kwargs.update(auth=(self.client_id, self.secret),
                          data={"grant_type": "client_credentials"})
        else:
            headers.update({"Authorization": f"Bearer {self.get_access_token()}",
                            "Content-Type": "application/json",
                            "Prefer": "return=representation"})
            request_id = request_id or str(uuid.uuid4())
            headers["PayPal-Request-Id"] = request_id
            if payload is not None:
                kwargs["json"] = payload
        try:
            # No automatic POST retries: a lost response may hide a completed payment.
            response = self._session.request(
                method, self.base_url + path, headers=headers,
                timeout=self.timeout, allow_redirects=False, **kwargs,
            )
        except requests.RequestException as exc:
            message = f"PayPal transport failure for {path}: {exc}"
            print(f"{message}\nPayPal debug ID: (no response)"
                  f"\nPayPal request ID: {request_id or '(not supplied)'}", file=sys.stderr)
            raise PayPalError(message, request_id=request_id) from exc
        if not 200 <= response.status_code < 300:
            self._fail(response, f"PayPal HTTP {response.status_code} for {path}", request_id)
        if response.status_code == 204:
            return {}
        try:
            result = response.json()
        except ValueError:
            self._fail(response, f"PayPal returned invalid JSON for {path}", request_id)
        if not isinstance(result, dict):
            self._fail(response, f"PayPal returned a non-object response for {path}", request_id)
        return result

    def get_access_token(self) -> str:
        """Fetch and cache a client-credentials Bearer token until near expiry."""
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token
        started_at = time.monotonic()
        result = self._request("/v1/oauth2/token", oauth=True)
        token = result.get("access_token")
        try:
            expires_in = float(result["expires_in"])
            if not expires_in > 0 or expires_in == float("inf"):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise PayPalError("PayPal token response has invalid/missing expires_in.") from exc
        if not isinstance(token, str) or not token:
            raise PayPalError("PayPal token response is missing access_token.")
        self._access_token = token
        self._token_expires_at = started_at + max(0, expires_in - 60)
        return token

    def create_session_hold(self, amount_usd: float, *,
                            request_id: str | None = None) -> tuple[str, str]:
        """Return (order_id, approve_url). The hold begins after authorization.

        PAY_NOW confirms the fixed authorization amount at PayPal. It does not
        capture funds: intent remains AUTHORIZE. The local return page performs
        independent status verification and never treats a redirect as approval.
        Reuse request_id only when retrying this same order and amount.
        """
        result = self._request("/v2/checkout/orders", request_id=request_id, payload={
            "intent": "AUTHORIZE",
            "purchase_units": [{"amount": self._amount(amount_usd)}],
            "payment_source": {"paypal": {"experience_context": {
                "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW",
                "return_url": self.return_url,
                "cancel_url": self.cancel_url,
            }}},
        })
        order_id = result.get("id")
        for link in result.get("links", []):
            if (isinstance(link, dict) and link.get("rel") in ("approve", "payer-action")
                    and isinstance(link.get("href"), str) and link["href"]
                    and isinstance(order_id, str) and order_id):
                return order_id, link["href"]
        raise PayPalError("PayPal create-order response is missing the order ID or approve URL.")

    def authorize_order(self, order_id: str, *, request_id: str | None = None) -> str:
        """Authorize an approved order and return its single authorization ID."""
        order_id = self._resource_id(order_id)
        result = self._request(f"/v2/checkout/orders/{order_id}/authorize",
                               payload={}, request_id=request_id)
        authorizations = [
            authorization
            for unit in result.get("purchase_units", [])
            for authorization in unit.get("payments", {}).get("authorizations", [])
        ]
        if (len(authorizations) != 1 or not authorizations[0].get("id")
                or authorizations[0].get("status") != "CREATED"):
            raise PayPalError("PayPal did not return exactly one CREATED authorization; inspect the order before capturing.")
        return authorizations[0]["id"]

    def capture_session_funds(self, authorization_id: str, amount_usd: float, *,
                              request_id: str | None = None) -> dict[str, Any]:
        """Capture the USD amount and release the uncaptured balance.

        Return the capture object. Check status: an accepted request can be PENDING.
        """
        authorization_id = self._resource_id(authorization_id)
        return self._request(
            f"/v2/payments/authorizations/{authorization_id}/capture",
            payload={"amount": self._amount(amount_usd), "final_capture": True},
            request_id=request_id,
        )

    def void_session(self, authorization_id: str, *,
                     request_id: str | None = None) -> None:
        """Void an uncaptured authorization when no queries were executed."""
        authorization_id = self._resource_id(authorization_id)
        self._request(f"/v2/payments/authorizations/{authorization_id}/void",
                      request_id=request_id)

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request(f"/v2/checkout/orders/{self._resource_id(order_id)}", method="GET")

    def get_capture(self, capture_id: str) -> dict[str, Any]:
        return self._request(f"/v2/payments/captures/{self._resource_id(capture_id)}", method="GET")

    def get_authorization(self, authorization_id: str) -> dict[str, Any]:
        return self._request(f"/v2/payments/authorizations/{self._resource_id(authorization_id)}", method="GET")
