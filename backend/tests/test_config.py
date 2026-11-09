import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize(
    "raw, expected",
    [("2030-01", "2030-01"), ("01/2030", "2030-01"), ("1/30", "2030-01"), ("12 / 2031", "2031-12"), ("", "")],
)
def test_card_expiry_is_normalised_to_paypal_format(raw, expected):
    assert Settings(_env_file=None, sandbox_card_expiry=raw).sandbox_card_expiry == expected


@pytest.mark.parametrize("raw", ["2030", "13/2030", "2030/01", "Jan 2030"])
def test_bad_card_expiry_is_rejected(raw):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, sandbox_card_expiry=raw)
