"""
Modus Light — Data Types & Contracts
====================================
Public domain schemas, types, and capability contracts.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List
import time


class AttenuationLevel(str, Enum):
    """
    Monotonic capability attenuation levels (L0 to L4).

    A delegated capability is ceilinged by the authority that lent it: reaching a
    resource through a `member_of` edge caps the result at the weakest edge on
    the path, so Level_child <= Level_parent. `ZanzibarReBAC.effective_level()`
    computes this; the ordering is defined by `ZanzibarReBAC.ATTENUATION_RANK`.

    The ceiling binds what the policy engine will authorize. It is not a sandbox:
    code that bypasses the engine and calls a tool directly is not constrained by
    a level, and the subject of a decision is a caller-supplied string, so
    authenticating the caller remains the application's job.
    """
    L0_UNAUTHENTICATED = "L0_UNAUTHENTICATED"
    L1_READ_ONLY = "L1_READ_ONLY"
    L2_STANDARD_OPERATOR = "L2_STANDARD_OPERATOR"
    L3_PRIVILEGED_AGENT = "L3_PRIVILEGED_AGENT"
    L4_SOVEREIGN_ENCLAVE = "L4_SOVEREIGN_ENCLAVE"


class ModelTier(str, Enum):
    """QoS Model Arbitrage Tiers."""
    FLASH_LITE = "flash_lite"      # Fast, deterministic tasks (<= 500 tokens)
    FLASH = "flash"                # Standard generation & tool dispatch (<= 2,000 tokens)
    PRO = "pro"                    # Complex planning & architecture (>= 8,000 tokens)


@dataclass
class CapabilityLease:
    """Cryptographic capability lease granted via Google Zanzibar ReBAC."""
    lease_id: str
    subject: str
    relation: str
    object_resource: str
    attenuation_level: AttenuationLevel
    granted_at: float
    expires_at: float
    signature: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return time.time() < self.expires_at


@dataclass
class TaskTuple:
    """Decoupled Linda coordinate tuple stored in the shared space."""
    id: int
    tenant_id: str
    topic: str
    payload: Dict[str, Any]
    priority: int = 0
    status: str = "PENDING"  # PENDING, LEASED, COMPLETED, FAILED
    lease_owner: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    #: When the current lease was taken. A worker that dies mid-task never calls
    #: complete(), so without a timestamp to age the lease against, the tuple
    #: stays LEASED forever and the work is silently dropped — invisible, because
    #: the queue reports it as in progress rather than failed.
    leased_at: Optional[float] = None


@dataclass
class ActorSpec:
    """Specification for an OTP-pattern supervised worker actor."""
    name: str
    role: str
    restart_policy: str = "transient"  # permanent, transient, temporary
    max_restarts: int = 3
    restart_window_seconds: float = 10.0
    depends_on: List[str] = field(default_factory=list)


@dataclass
class AuditReport:
    """
    Smoke audit verification report.

    Every field is measured at runtime. `findings` carries the name of each
    failed check so a non-PASSED report is actionable.
    """
    timestamp: str
    checks_total: int
    checks_passed: int
    checks_failed: int
    duration_seconds: float
    wire_tokens_consumed: int
    symlink_count: int
    findings: List[str] = field(default_factory=list)
    status: str = "PASSED"
