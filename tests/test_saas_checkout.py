from bot.handlers.user.payments.saas import (
    _matching_accesses,
    _matching_local_tariffs,
    _key_matches_material,
    _parse_checkout_callback,
    _parse_single_value_callback,
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


def test_parse_new_access_callbacks():
    assert _parse_single_value_callback(
        "saas_new_checkout:tariff-123",
        "saas_new_checkout",
    ) == "tariff-123"
    assert _parse_single_value_callback("wrong:tariff-123", "saas_new_checkout") is None
    assert _parse_single_value_callback("saas_new_checkout:", "saas_new_checkout") is None


def test_local_tariff_mapping_requires_exact_commercial_shape():
    saas = {
        "duration_days": 2,
        "price_rub": 100,
        "device_limit": 1,
        "traffic_limit_gb": 2,
    }
    local = [
        {"id": 1, "duration_days": 2, "price_rub": 100, "max_ips": 1, "traffic_limit_gb": 2},
        {"id": 2, "duration_days": 2, "price_rub": 100, "max_ips": 2, "traffic_limit_gb": 2},
    ]
    assert _matching_local_tariffs(local, saas) == [local[0]]


def test_key_material_match_is_exact():
    key = {
        "panel_email": "wm_access_1_1",
        "client_uuid": "f5ee70ce-8a27-4f15-b81e-edc8a8bd11c4",
        "sub_id": "abcdefghijklmnop",
        "panel_inbound_id": 9,
    }
    material = {
        "panel_email": "wm_access_1_1",
        "client_uuid": "f5ee70ce-8a27-4f15-b81e-edc8a8bd11c4",
        "sub_id": "abcdefghijklmnop",
        "primary_inbound_id": 9,
    }
    assert _key_matches_material(key, material)
    assert not _key_matches_material(key, {**material, "sub_id": "replacement"})
