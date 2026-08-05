from __future__ import annotations

from pathlib import Path


helper = Path("tools/apply_direct_subscription_delivery.py")
source = helper.read_text(encoding="utf-8")
old = "    '''    VerifiedReadyPaymentReturn,\n    materialize_ready_payment_return,\n"
new = (
    "    '''    PaymentReturnMaterialization,\n"
    "    VerifiedReadyPaymentReturn,\n"
    "    materialize_ready_payment_return,\n"
)
if old not in source:
    raise RuntimeError("test import patch anchor not found")
corrected = source.replace(old, new, 1)
exec(compile(corrected, str(helper), "exec"), {"__name__": "__main__"})
