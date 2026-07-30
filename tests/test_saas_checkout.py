from bot.handlers.user.payments.saas import (
    _matching_accesses,
    _parse_checkout_callback,
    _tariff_button_text,
)


def test_matching_accesses_requires_explicit_legacy_key_mapping():
    accesses = [
        {"access_id": "access-1", "legacy_key_id": "3"},
        {"access_id": "access-2", "legacy_key_id": "4"},
        {"access_id": "access-3"},
    ]

    assert _matching_accesses(accesses, 3) == [
        {"access_id": "access-1", "legacy_key_id": "3"}
    ]
    assert _matching_accesses(accesses, 99) == []
    assert _matching_accesses(None, 3) == []


def test_parse_checkout_callback():
    assert _parse_checkout_callback("saas_checkout:3:tariff-123") == (
        3,
        "tariff-123",
    )
    assert _parse_checkout_callback("legacy:3:tariff-123") is None
    assert _parse_checkout_callback("saas_checkout:not-an-int:tariff-123") is None
    assert _parse_checkout_callback("saas_checkout:3:") is None


def test_tariff_button_text():
    assert _tariff_button_text(
        {
            "name": "Месяц",
            "duration_days": 30,
            "price_rub": 299,
        }
    ) == "Месяц · 30 дн. · 299 ₽"
