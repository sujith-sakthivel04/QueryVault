from decimal import Decimal
from unittest.mock import patch
import pytest
from paypal_client import PayPalClient
from verify_approved_session import CappedSandboxClient


@pytest.mark.parametrize('amount',[Decimal('0.01'),Decimal('1.05'),Decimal('8.40')])
def test_specific_capture_cap_accepts_authorized_amounts(amount,monkeypatch):
    monkeypatch.setenv('PAYPAL_CLIENT_ID','mock-client')
    monkeypatch.setenv('PAYPAL_SECRET','mock-secret')
    monkeypatch.setenv('PAYPAL_ENVIRONMENT','sandbox')
    with CappedSandboxClient() as client,patch.object(PayPalClient,'capture_session_funds',return_value={'status':'MOCK'}) as call:
        client.capture_session_funds('AUTH1',amount,request_id='stable')
        call.assert_called_once_with('AUTH1',amount,request_id='stable')


@pytest.mark.parametrize('amount',[Decimal('0'),Decimal('-1'),Decimal('8.41'),Decimal('20')])
def test_specific_capture_cap_blocks_unapproved_amounts(amount,monkeypatch):
    monkeypatch.setenv('PAYPAL_CLIENT_ID','mock-client')
    monkeypatch.setenv('PAYPAL_SECRET','mock-secret')
    monkeypatch.setenv('PAYPAL_ENVIRONMENT','sandbox')
    with CappedSandboxClient() as client,patch.object(PayPalClient,'capture_session_funds') as call:
        with pytest.raises(ValueError): client.capture_session_funds('AUTH1',amount)
        call.assert_not_called()
