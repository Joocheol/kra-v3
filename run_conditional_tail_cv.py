#!/usr/bin/env python3
"""Run conditional-tail CV with Decimal-compatible virtual caps."""
from decimal import Decimal

import analyze_conditional_tail_cv as audit

_original = audit.capped_ticket_upper


def _decimal_cap(sales, *, cap):
    if not isinstance(cap, Decimal):
        cap = Decimal(str(cap))
    return _original(sales, cap=cap)


audit.capped_ticket_upper = _decimal_cap
raise SystemExit(audit.main())
