"""
Modus Light — Exceptions
========================
Standard domain exceptions for Modus Light runtime errors.
"""


class ModusError(Exception):
    """Base exception for all Modus Light errors."""
    pass


class AuthorizationDeniedError(ModusError):
    """Raised when Zanzibar ReBAC policy denies capability access."""
    pass


class SpendCapExceededError(ModusError):
    """Raised when Step 5 Pre-Dispatch FinOps Kill Switch halts token overspend."""
    pass


class ReservationCeilingBreachedError(SpendCapExceededError):
    """
    Raised when a step settles above the ceiling it was granted.

    A subclass, so existing `except SpendCapExceededError` handlers keep working,
    but distinguishable because the two cases need opposite responses: a refused
    dispatch cost nothing and can be retried with a smaller estimate, whereas this
    means the tokens are already spent and the ceiling did not bind the provider
    call. Pass `reservation.max_tokens` as the provider's output limit to stop it
    recurring.
    """
    pass


class MemoryPoisoningError(ModusError):
    """Raised when MINJA/GhostWriter prompt injection or memory contamination is detected."""
    pass


class DualCustodyRequiredError(ModusError):
    """Raised when a high-risk operation requires 2-person cryptographic quorum."""
    pass


class ActorCrashError(ModusError):
    """Raised when an actor encounters an unhandled panic during execution."""
    pass


class ConfigurationError(ModusError):
    """Raised when runtime configuration (e.g. a spend ceiling) is malformed."""
    pass


class CircuitBreakerTrippedError(ModusError):
    """Raised when actor crash frequency exceeds OTP supervisor threshold."""
    pass
