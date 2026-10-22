"""
Modus Light — Sovereign Enterprise Agent Runtime (Community Edition)
====================================================================
Lightweight, zero-token agent orchestration engine with Google Zanzibar ReBAC,
algorithmic FinOps Step 5 kill switches, and Erlang OTP supervisor fault trees.
"""

__version__ = "1.0.0"
__author__ = "Modus Labs & Sovereign Systems"
# SPDX identifier, matching `license = "BUSL-1.1"` in pyproject.toml. Spelled out
# because "BSL" is the Boost Software License — a permissive licence — and an
# inventory tool keying on this string must not record a source-available product
# as permissively licensed.
__license__ = "BUSL-1.1"  # Business Source License 1.1

from .client import ModusLight
from .token_shield import TokenShield
from .finops import FinOpsGateway
from .rebac import ZanzibarReBAC
from .linda import TupleSpace
from .supervisor import OtpSupervisor
from .types import (
    TaskTuple,
    CapabilityLease,
    ActorSpec,
    AuditReport,
    AttenuationLevel,
    ModelTier,
)
from .exceptions import (
    ModusError,
    AuthorizationDeniedError,
    SpendCapExceededError,
    ReservationCeilingBreachedError,
    MemoryPoisoningError,
    DualCustodyRequiredError,
    ActorCrashError,
    CircuitBreakerTrippedError,
    ConfigurationError,
)

__all__ = [
    "ModusLight",
    "TokenShield",
    "FinOpsGateway",
    "ZanzibarReBAC",
    "TupleSpace",
    "OtpSupervisor",
    "TaskTuple",
    "CapabilityLease",
    "ActorSpec",
    "AuditReport",
    "AttenuationLevel",
    "ModelTier",
    "ModusError",
    "AuthorizationDeniedError",
    "SpendCapExceededError",
    "ReservationCeilingBreachedError",
    "MemoryPoisoningError",
    "DualCustodyRequiredError",
    "ActorCrashError",
    "CircuitBreakerTrippedError",
    "ConfigurationError",
]
