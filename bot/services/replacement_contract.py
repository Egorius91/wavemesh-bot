"""Strict, bounded replacement contracts; no transport or framework dependencies."""
import re

COMMAND_STATUSES = frozenset({"PENDING", "LEASED", "RUNNING", "SUCCEEDED", "RETRYABLE_FAILED",
                              "PERMANENT_FAILED", "ROLLED_BACK", "ROLLBACK_FAILED", "CANCELLED"})
TERMINAL_FAILURES = frozenset({"PERMANENT_FAILED", "ROLLED_BACK", "ROLLBACK_FAILED", "CANCELLED"})


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("INVALID_REPLACEMENT_IDENTITY")
    return value


def request_values(access_id, request_key, expected_version):
    identity(access_id)
    if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", request_key):
        raise ValueError("INVALID_REPLACEMENT_KEY")
    if type(expected_version) is not int or not 1 <= expected_version <= 2_147_483_646:
        raise ValueError("INVALID_REPLACEMENT_VERSION")


def reference(result, expected_version):
    if (not isinstance(result, dict) or result.get("status") not in {s.lower() for s in COMMAND_STATUSES}
            or type(result.get("desired_version")) is not int or result["desired_version"] != expected_version+1):
        raise ValueError("INVALID_REPLACEMENT_REFERENCE")
    return {"command_id": identity(result.get("command_id")), "status": result["status"],
            "desired_version": result["desired_version"]}


def readback(result, access_id, expected_version):
    if (not isinstance(result, dict) or result.get("can_retry_replace") is not False
            or result.get("request_status") not in {"PROCESSING", "SUCCEEDED", "FAILED"}):
        raise ValueError("INVALID_REPLACEMENT_READBACK")
    safe = {"request_id": identity(result.get("request_id")), "request_status": result["request_status"],
            "submission": result.get("submission"), "status": result.get("status"), "can_retry_replace": False}
    if safe["submission"] == "UNCONFIRMED":
        if (safe["status"] not in {"PENDING", "TIMEOUT", "MANUAL_REVIEW"}
                or any(f not in result or result[f] is not None for f in ("access_id", "command_id", "assigned_entry_node_id", "desired_version"))):
            raise ValueError("INVALID_REPLACEMENT_READBACK")
        safe.update(access_id=None, command_id=None, assigned_entry_node_id=None, desired_version=None)
        return safe
    if (safe["submission"] != "OBSERVED" or safe["status"] not in {"PENDING", "READY", "FAILED", "SUPERSEDED"}
            or result.get("access_id") != access_id or type(result.get("desired_version")) is not int
            or result["desired_version"] != expected_version+1 or result.get("command_status") not in COMMAND_STATUSES
            or (safe["status"] == "READY" and result["command_status"] != "SUCCEEDED")):
        raise ValueError("INVALID_REPLACEMENT_READBACK")
    safe.update(access_id=access_id, desired_version=result["desired_version"], command_status=result["command_status"],
                command_id=identity(result.get("command_id")), assigned_entry_node_id=identity(result.get("assigned_entry_node_id")))
    return safe
