"""Bounded SaaS checkout snapshots. No provider or VPN identifiers are retained."""
import re
from urllib.parse import urlsplit


class CheckoutContractError(ValueError):
    pass


TERMINAL = frozenset({"PAID", "CANCELLED", "REFUNDED"})


def rejection_proof(value):
    if (not isinstance(value, dict)
            or set(value) != {"version", "checkoutKind", "outcome", "final", "allowNewCreate"}
            or type(value.get("version")) is not int or value["version"] != 1
            or value.get("checkoutKind") != "INITIAL_SAVED" or value.get("outcome") != "NOT_ADMITTED"
            or value.get("final") is not True or value.get("allowNewCreate") is not False):
        raise CheckoutContractError("INVALID_CHECKOUT_REJECTION")
    return True


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", value):
        raise CheckoutContractError("INVALID_CHECKOUT_IDENTITY")
    return value


def request_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", value):
        raise CheckoutContractError("INVALID_CHECKOUT_KEY")
    return value


def consent(value):
    fields = {"version", "amountRub", "durationDays", "deviceLimit", "trafficLimitGb"}
    if not isinstance(value, dict) or set(value) != fields or type(value["version"]) is not int or value["version"] != 1:
        raise CheckoutContractError("INVALID_CHECKOUT_CONSENT")
    for field in ("amountRub", "durationDays", "deviceLimit", "trafficLimitGb"):
        v = value[field]
        if field == "trafficLimitGb" and v is None:
            continue
        if type(v) is not int or not (1 if field in {"amountRub", "durationDays"} else 0) <= v <= 2**53-1:
            raise CheckoutContractError("INVALID_CHECKOUT_CONSENT")
    return {field: value[field] for field in sorted(fields)}


def tariff(value):
    if not isinstance(value, dict) or value.get("billing_mode") != "RECURRING":
        raise CheckoutContractError("INVALID_CHECKOUT_TARIFF")
    name = value.get("name")
    if not isinstance(name, str) or not name or len(name) > 300:
        raise CheckoutContractError("INVALID_CHECKOUT_TARIFF")
    return {"tariff_id": identity(value.get("tariff_id")), "name": name, "recurring_consent": consent({
        "version": 1, "amountRub": value.get("price_rub"), "durationDays": value.get("duration_days"),
        "deviceLimit": value.get("device_limit"), "trafficLimitGb": value.get("traffic_limit_gb"),
    })}


def snapshot(value, *, current=False):
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1 or value.get("allowNewCreate") is not False:
        raise CheckoutContractError("INVALID_CHECKOUT_SNAPSHOT")
    if current and value.get("current", False) is None:
        if set(value) != {"version", "current", "allowNewCreate"}:
            raise CheckoutContractError("INVALID_CHECKOUT_SNAPSHOT")
        return None
    order_id = identity(value.get("orderId"))
    status = value.get("paymentStatus")
    if not isinstance(status, str) or status not in TERMINAL | {"PREPARING", "PENDING"}:
        raise CheckoutContractError("INVALID_CHECKOUT_STATUS")
    terms = value.get("terms")
    if not isinstance(terms, dict) or terms.get("purchaseKind") not in {"NEW_ACCESS", "RENEWAL"}:
        raise CheckoutContractError("INVALID_CHECKOUT_TERMS")
    parsed = tariff({"billing_mode": "RECURRING", "tariff_id": terms.get("tariffId"), "name": terms.get("name"),
                     "price_rub": terms.get("amountRub"), "duration_days": terms.get("durationDays"),
                     "device_limit": terms.get("deviceLimit"), "traffic_limit_gb": terms.get("trafficLimitGb")})
    url = value.get("checkoutUrl", False)
    if url is not None:
        if not isinstance(url, str) or not url or len(url) > 4096 or any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
            raise CheckoutContractError("INVALID_CHECKOUT_URL")
        try:
            split = urlsplit(url)
            valid = split.scheme == "https" and bool(split.hostname) and not split.username and not split.password
            _ = split.port
        except ValueError:
            valid = False
        if not valid or status != "PENDING":
            raise CheckoutContractError("INVALID_CHECKOUT_URL")
    entitlement = value.get("entitlement")
    if not isinstance(entitlement, dict) or not isinstance(entitlement.get("status"), str) or len(entitlement["status"]) > 64:
        raise CheckoutContractError("INVALID_CHECKOUT_ENTITLEMENT")
    access = value.get("access", False)
    if access is not None and (not isinstance(access, dict) or type(access.get("configurationReady")) is not bool):
        raise CheckoutContractError("INVALID_CHECKOUT_ACCESS")
    recurring = value.get("recurring")
    if not isinstance(recurring, str) or len(recurring) > 64:
        raise CheckoutContractError("INVALID_CHECKOUT_RECURRING")
    # Return a new allow-listed view, never the entire upstream payload.
    return {"order_id": order_id, "payment_status": status, "checkout_url": url, "terms": parsed,
            "purchase_kind": terms["purchaseKind"], "entitlement_status": entitlement["status"],
            "configuration_ready": access["configurationReady"] if access else False, "recurring": recurring}
