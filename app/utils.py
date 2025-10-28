from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, getcontext, ROUND_HALF_UP
import itertools
import logging
import os
from typing import Any, Dict

# Decimal configuration for financial calculations
getcontext().prec = 28
getcontext().rounding = ROUND_HALF_UP

_DECIMAL_QUANT = Decimal("0.00000001")

_id_counter = itertools.count(1)


def now_ts() -> str:
    """Return a UTC ISO8601 timestamp with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def as_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_8(d: Decimal) -> Decimal:
    return d.quantize(_DECIMAL_QUANT)


def next_id(prefix: str = "ord") -> str:
    return f"{prefix}_{next(_id_counter)}"


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=(
            "%(asctime)sZ %(levelname)s %(name)s "
            "event=%(message)s extra=%(extra)s"
        ),
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


class StructuredAdapter(logging.LoggerAdapter):
    def process(self, msg: str, kwargs: Dict[str, Any]):
        extra = kwargs.get("extra", {})
        kwargs["extra"] = {"extra": extra}
        return msg, kwargs
