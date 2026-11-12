"""Resume the specifically approved Sandbox research session without new orders.

Capture is independently capped at $8.40 by the payment adapter. Journaled agent
attempts are not automatically rerun if their response/result is uncertain.
"""
import json
from decimal import Decimal
from pathlib import Path

from agent import research
from engine import Engine
from paypal_client import PayPalClient

SID = "PRIVATE_OPERATOR_REFERENCE_REQUIRED"
ORDER = "PRIVATE_OPERATOR_REFERENCE_REQUIRED"
OWNER = "local-operator"
CAP_CENTS = 840
PATH = Path(".local/real-session-evidence.json")


class CappedSandboxClient(PayPalClient):
    def capture_session_funds(self, authorization_id, amount_usd, **kwargs):
        if not Decimal("0") < Decimal(str(amount_usd)) <= Decimal("8.40"):
            raise ValueError("This verified workflow may capture at most $8.40")
        return super().capture_session_funds(authorization_id, amount_usd, **kwargs)


def main():
    raise SystemExit('Historical payment runner is disabled in the public source. Use the local workspace only after explicit operator approval.')

if __name__=='__main__': main()
