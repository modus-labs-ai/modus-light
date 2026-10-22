"""
Modus Light — FinOps Pre-Dispatch Gateway
=========================================
Algorithmic token spend governance and pre-dispatch Step 5 kill switches.
Halts runaway agent loops before any API call occurs.

Scope of the guarantee, in three parts:

* A refused step never dispatches, so it spends nothing.
* An admitted step is ceilinged at the provider: `reservation.max_tokens` is the
  generation budget with the prompt already deducted, so prompt plus output cannot
  exceed what the step reserved.
* Settling above that ceiling raises `SpendCapExceededError` and increments
  `ceiling_breaches`, rather than being absorbed.

Spend therefore cannot exceed reservations, and `reserve()` refuses anything above
the remaining budget, so reservations cannot exceed the cap. $0.00 overdraft is an
arithmetic consequence of those two facts for every step that settles through its
reservation within its ceiling.

Outside that: a caller who commits spend anonymously (no reservation), or who sets
`enforce_reservation_ceiling=False`, is not covered. For those paths the overrun is
measured and reported as `overdraft_tokens` / `overdraft_amount` rather than
assumed away.

Spend model: an authorized step *reserves* its estimated token cost against
the cap before dispatch. The reservation is settled by commit_spend() (actual
cost) or released when the step is abandoned.
"""

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from .types import ModelTier
from .exceptions import ReservationCeilingBreachedError, SpendCapExceededError


def _validate_tokens(value: Any, label: str) -> int:
    """
    Coerces a token count to a non-negative finite int, or raises ValueError.

    This is a security boundary, not defensive politeness. A spend ceiling is
    enforced by the comparison `current + estimated > cap`, and that comparison
    can be defeated two ways by an unvalidated number:

    * a negative value passes the gate and *credits* the budget, so
      `reserve(-10**9)` restores unlimited headroom;
    * `float("nan")` makes every comparison against it False, so the gate can
      never trip again for that value.

    A kill switch that can be disabled by its own argument is not a kill switch,
    so anything that is not a real, finite, non-negative count is refused here —
    before it can reach the arithmetic.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a non-negative integer, got {value!r}")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label} must be finite, got {value!r}")
        if value != int(value):
            raise ValueError(f"{label} must be a whole number of tokens, got {value!r}")
    if value < 0:
        raise ValueError(f"{label} must be non-negative, got {value!r}")
    return int(value)


@dataclass(eq=False)
class SpendReservation:
    """Tokens held against the spend cap by an authorized, not-yet-dispatched step.

    `eq=False` so each handle compares by identity. With dataclass equality, two
    distinct reservations sharing an amount, tier and `created_at` — ordinary for
    concurrent callers on a coarse clock — are indistinguishable, and a caller
    settling one would release the other's hold on the cap.
    """
    amount: int
    created_at: float
    tier: ModelTier = ModelTier.FLASH
    #: Set once the reservation has been committed or released. A reservation is
    #: a one-shot claim on the budget: without this flag the same handle could be
    #: committed repeatedly, each pass decrementing the global reserve again and
    #: silently freeing another step's hold.
    settled: bool = field(default=False)
    #: Tokens of this reservation already committed to the prompt. Providers bill
    #: input *and* output, so a ceiling that ignores the prompt is not a ceiling:
    #: handing the provider the full reservation as its output limit lets the step
    #: cost prompt + reservation and breach on every call.
    prompt_tokens: int = field(default=0)

    @property
    def max_tokens(self) -> int:
        """
        The output limit to hand the provider, with the prompt already deducted.

        Pass this as the provider's `max_tokens` (or equivalent). That is what
        turns the reservation from a prediction into a bound: prompt plus the most
        the provider is allowed to generate cannot exceed what this step reserved.

        Declare the prompt via `reserve(..., prompt_tokens=N)`. Left at zero this
        equals the whole reservation, which only binds the call if the caller
        budgets for the prompt some other way.
        """
        return self.amount - self.prompt_tokens


class FinOpsGateway:
    """
    FinOps Pre-Dispatch Gateway:
    Monitors token burn in real time and trips a hard kill switch
    if a proposed execution step exceeds allocated budget.
    """

    # Industry standard blended costs per 1,000 tokens (for reference & reporting)
    TIER_PRICING = {
        ModelTier.FLASH_LITE: 0.0001,  # $0.10 / 1M
        ModelTier.FLASH: 0.0004,       # $0.40 / 1M
        ModelTier.PRO: 0.0050,         # $5.00 / 1M
    }

    def __init__(
        self,
        spend_cap_tokens: int = 50000,
        enforce_reservation_ceiling: bool = True,
    ):
        self.spend_cap_tokens = _validate_tokens(spend_cap_tokens, "spend_cap_tokens")
        # When True, settling a step above its granted ceiling raises. This is what
        # makes the overdraft bound real: without it the cap governs only the
        # estimate a caller volunteered, and any step can quietly exceed it.
        self.enforce_reservation_ceiling = enforce_reservation_ceiling
        self._ceiling_breaches = 0
        self._spent_tokens = 0
        self._reserved_tokens = 0
        self._total_requests = 0
        self._tokens_saved_estimate = 0
        self._last_tier = ModelTier.FLASH
        # Cost is accrued in dollars at the moment each step settles, at the tier
        # that step actually ran on. Deriving it later from a running token total
        # and the most recent tier would reprice all historical spend every time
        # the tier changed — one PRO step at the end would restate every earlier
        # FLASH_LITE token at 50x its real price.
        self._spend_usd = 0.0
        self._savings_usd = 0.0
        self._lock = threading.Lock()

    @property
    def current_spend(self) -> int:
        """Tokens consumed plus tokens reserved but not yet settled."""
        return self._spent_tokens + self._reserved_tokens

    @property
    def remaining_budget(self) -> int:
        return max(0, self.spend_cap_tokens - self.current_spend)

    def pre_dispatch_check(self, estimated_tokens: int) -> bool:
        """
        Step 5 Spend Kill Switch:
        Evaluates token budget BEFORE dispatching requests to LLMs.
        Raises SpendCapExceededError if adding estimated_tokens violates spend_cap_tokens.
        This check does not consume budget; use reserve() for that.
        """
        estimated_tokens = _validate_tokens(estimated_tokens, "estimated_tokens")
        with self._lock:
            if self.current_spend + estimated_tokens > self.spend_cap_tokens:
                raise SpendCapExceededError(
                    f"Step 5 FinOps Kill Switch Tripped: Adding {estimated_tokens} tokens "
                    f"exceeds spend cap of {self.spend_cap_tokens} (Current: {self.current_spend}). "
                    f"Refused before dispatch; this step spends nothing."
                )
            return True

    def reserve(
        self,
        estimated_tokens: int,
        tier: ModelTier = ModelTier.FLASH,
        prompt_tokens: int = 0,
    ) -> SpendReservation:
        """
        Reserves estimated tokens against the spend cap and returns the reservation.
        The reservation must be settled with commit_spend() or released with release().

        `estimated_tokens` is the whole step — prompt plus generation. Declaring
        `prompt_tokens` lets `reservation.max_tokens` come back as the generation
        budget that actually remains, which is the number a provider can enforce.
        """
        estimated_tokens = _validate_tokens(estimated_tokens, "estimated_tokens")
        prompt_tokens = _validate_tokens(prompt_tokens, "prompt_tokens")
        if prompt_tokens >= estimated_tokens and prompt_tokens > 0:
            # Refused rather than clamped to zero: a reservation whose prompt
            # already consumes the whole allowance cannot be honoured by any
            # output limit, so the step would breach its ceiling the moment it ran.
            raise ValueError(
                f"prompt_tokens ({prompt_tokens}) leaves no generation budget "
                f"within estimated_tokens ({estimated_tokens}); raise the estimate "
                f"or shorten the prompt"
            )
        with self._lock:
            if self.current_spend + estimated_tokens > self.spend_cap_tokens:
                raise SpendCapExceededError(
                    f"Step 5 FinOps Kill Switch Tripped: Adding {estimated_tokens} tokens "
                    f"exceeds spend cap of {self.spend_cap_tokens} (Current: {self.current_spend}). "
                    f"Refused before dispatch; this step spends nothing."
                )
            self._reserved_tokens += estimated_tokens
            self._last_tier = tier
            return SpendReservation(
                amount=estimated_tokens,
                created_at=time.time(),
                tier=tier,
                prompt_tokens=prompt_tokens,
            )

    def commit_spend(
        self,
        actual_tokens: int,
        reservation: Optional[SpendReservation] = None,
        tokens_saved: int = 0,
        tier: Optional[ModelTier] = None,
    ) -> int:
        """
        Records verified token consumption and tracked savings after execution.
        The matching reservation (if any) is settled at the same time.

        A reservation settles exactly once: passing an already-settled handle
        raises ValueError rather than releasing its hold a second time.

        Cost is accrued here, at the tier this step ran on — taken from the
        reservation when one is supplied, otherwise from `tier`, otherwise the
        last tier seen.
        """
        actual_tokens = _validate_tokens(actual_tokens, "actual_tokens")
        tokens_saved = _validate_tokens(tokens_saved, "tokens_saved")

        if reservation is not None and reservation.settled:
            raise ValueError(
                "this reservation has already been settled; a reservation is a "
                "one-shot claim on the budget and cannot be committed twice"
            )

        if (
            self.enforce_reservation_ceiling
            and reservation is not None
            and actual_tokens > reservation.amount
        ):
            # The ceiling is refused loudly rather than absorbed. Accepting this
            # silently is what turns a bounded budget into an advisory one: the
            # tokens are already gone, and the only remaining question is whether
            # the operator finds out now or from an invoice later.
            with self._lock:
                reservation.settled = True
                self._reserved_tokens = max(0, self._reserved_tokens - reservation.amount)
                self._spent_tokens += actual_tokens
                self._total_requests += 1
                self._ceiling_breaches += 1
                price = self.TIER_PRICING[reservation.tier]
                self._spend_usd += (actual_tokens / 1000.0) * price
            raise ReservationCeilingBreachedError(
                f"Reservation ceiling breached: the step settled at {actual_tokens} "
                f"tokens against a granted ceiling of {reservation.amount}. The spend "
                f"is recorded, and `ceiling_breaches` is now "
                f"{self._ceiling_breaches}. Pass `reservation.max_tokens` to the "
                f"provider as its output limit so the ceiling binds the call itself."
            )

        with self._lock:
            if reservation is not None:
                released = reservation.amount
                reservation.settled = True
                effective_tier = reservation.tier
            else:
                released = min(self._reserved_tokens, actual_tokens)
                effective_tier = tier or self._last_tier

            self._reserved_tokens = max(0, self._reserved_tokens - released)
            self._spent_tokens += actual_tokens
            self._total_requests += 1
            self._tokens_saved_estimate += tokens_saved

            price = self.TIER_PRICING[effective_tier]
            self._spend_usd += (actual_tokens / 1000.0) * price
            self._savings_usd += (tokens_saved / 1000.0) * price
            return self._spent_tokens

    def release(self, reservation: SpendReservation) -> None:
        """
        Releases a reservation back to the budget (step abandoned, never dispatched).

        Releasing an already-settled reservation is a no-op rather than an error,
        so a `finally:` block can release unconditionally without having to know
        whether the step committed.
        """
        with self._lock:
            if reservation.settled:
                return
            reservation.settled = True
            self._reserved_tokens = max(0, self._reserved_tokens - reservation.amount)

    def recommend_tier(self, prompt_tokens: int, requires_deep_planning: bool = False) -> ModelTier:
        """
        QoS Model Arbitrage:
        Recommends cost-optimal model tier based on task complexity.
        """
        if requires_deep_planning or prompt_tokens > 4000:
            return ModelTier.PRO
        elif prompt_tokens <= 500:
            return ModelTier.FLASH_LITE
        else:
            return ModelTier.FLASH

    def get_finops_summary(self) -> Dict[str, Any]:
        """Returns the real-time financial telemetry report."""
        with self._lock:
            est_cost = self._spend_usd
            est_saved_usd = self._savings_usd
            # Measured, not asserted. Every step that settles through its
            # reservation within its ceiling leaves this at zero by construction,
            # so on the supported path it reads 0 because it *is* 0. It is computed
            # rather than hard-coded for the paths the ceiling does not cover —
            # anonymous commits and `enforce_reservation_ceiling=False` — where a
            # hard-coded 0.0 would report no overdraft at precisely the moment the
            # tenant went over budget.
            overdraft_tokens = max(0, self._spent_tokens - self.spend_cap_tokens)
            overdraft_usd = (overdraft_tokens / 1000.0) * self.TIER_PRICING[self._last_tier]
            return {
                "spend_cap_tokens": self.spend_cap_tokens,
                "consumed_tokens": self._spent_tokens,
                "reserved_tokens": self._reserved_tokens,
                "remaining_tokens": self.remaining_budget,
                "total_requests": self._total_requests,
                "tokens_saved_estimate": self._tokens_saved_estimate,
                "last_tier": self._last_tier.value,
                "estimated_spend_usd": round(est_cost, 4),
                "estimated_savings_usd": round(est_saved_usd, 4),
                "overdraft_tokens": overdraft_tokens,
                "overdraft_amount": round(overdraft_usd, 4),
                # Steps that settled above their granted ceiling. Zero means the
                # $0.00 overdraft guarantee held for every step in this run.
                "ceiling_breaches": self._ceiling_breaches,
            }
