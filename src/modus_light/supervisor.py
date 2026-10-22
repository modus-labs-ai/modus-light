"""
Modus Light — OTP Supervisor Lite
==================================
Lightweight actor supervision with self-healing fault trees,
ONE_FOR_ONE / REST_FOR_ONE recovery strategies, and automated crash dampening.

This is a Python implementation of the OTP supervisor *pattern*: restart
policies, restart intensity windows and circuit breaking are real and
enforced here. It does not link against BEAM/Erlang.
"""

import time
import threading
from typing import Dict, List, Callable, Any
from .types import ActorSpec
from .exceptions import ActorCrashError, CircuitBreakerTrippedError


class OtpSupervisor:
    """
    OTP-pattern Actor Supervisor:
    Supervises worker actors, isolates unhandled panics, restarts crashed
    actors within a restart-intensity budget, and trips a circuit breaker
    when an actor exceeds that budget.
    """

    def __init__(self, strategy: str = "one_for_one", max_restarts: int = 3, window_seconds: float = 10.0):
        if strategy not in ("one_for_one", "rest_for_one"):
            raise ValueError(f"Unknown supervision strategy '{strategy}'. Use 'one_for_one' or 'rest_for_one'.")
        self.strategy = strategy
        self.max_restarts = max_restarts
        self.window_seconds = window_seconds

        self._specs: Dict[str, ActorSpec] = {}
        self._handlers: Dict[str, Callable[..., Any]] = {}
        self._restart_history: Dict[str, List[float]] = {}
        self._status: Dict[str, str] = {}  # RUNNING, RESTARTING, FAILED, TRIPPED
        self._lock = threading.Lock()

    def register_actor(self, spec: ActorSpec, handler: Callable[..., Any]):
        """Registers a worker actor under supervisor management."""
        with self._lock:
            self._specs[spec.name] = spec
            self._handlers[spec.name] = handler
            self._restart_history[spec.name] = []
            self._status[spec.name] = "RUNNING"

    def _limit_for(self, actor_name: str) -> int:
        spec = self._specs.get(actor_name)
        return spec.max_restarts if spec else self.max_restarts

    def _window_for(self, actor_name: str) -> float:
        spec = self._specs.get(actor_name)
        return spec.restart_window_seconds if spec else self.window_seconds

    def execute_actor(self, actor_name: str, *args, **kwargs) -> Any:
        """
        Executes an actor under supervision.

        A crashing handler is isolated and the actor is restarted in place,
        up to the restart-intensity budget (`max_restarts` inside
        `restart_window_seconds`). When the budget is exhausted the circuit
        breaker trips and the actor is taken out of service.
        """
        with self._lock:
            if actor_name not in self._specs:
                raise KeyError(f"Actor '{actor_name}' is not registered under supervisor.")
            if self._status[actor_name] == "TRIPPED":
                raise CircuitBreakerTrippedError(
                    f"Supervisor Circuit Breaker Tripped: Actor '{actor_name}' exceeded "
                    f"{self._limit_for(actor_name)} restarts in {self._window_for(actor_name)}s. "
                    f"Execution halted."
                )
        handler = self._handlers[actor_name]

        while True:
            try:
                result = handler(*args, **kwargs)
            except Exception as exc:
                # Raises when the actor must be taken out of service.
                self._handle_actor_crash(actor_name, exc)
                continue
            with self._lock:
                self._status[actor_name] = "RUNNING"
            return result

    def _handle_actor_crash(self, actor_name: str, exc: Exception) -> None:
        """
        Isolates a crash and applies the restart policy.

        Returns when the actor should be restarted (the caller retries the
        handler). Raises ActorCrashError or CircuitBreakerTrippedError when the
        actor is taken out of service.
        """
        now = time.time()
        with self._lock:
            spec = self._specs[actor_name]
            limit = self._limit_for(actor_name)
            window = self._window_for(actor_name)

            # Restart intensity: prune restarts that fell outside the window
            history = [t for t in self._restart_history.get(actor_name, []) if now - t <= window]

            if spec.restart_policy == "temporary":
                # Temporary actors are never restarted
                self._restart_history[actor_name] = history
                self._status[actor_name] = "FAILED"
                raise ActorCrashError(
                    f"Actor '{actor_name}' panic isolated by supervisor: {exc}"
                ) from exc

            if len(history) >= limit:
                self._restart_history[actor_name] = history
                self._status[actor_name] = "TRIPPED"
                raise CircuitBreakerTrippedError(
                    f"Supervisor Circuit Breaker Tripped: Actor '{actor_name}' crashed "
                    f"{len(history)} times in {window}s (Max: {limit}). "
                    f"Root panic: {exc}"
                ) from exc

            history.append(now)
            self._restart_history[actor_name] = history
            self._status[actor_name] = "RESTARTING"

            if self.strategy == "rest_for_one":
                self._restart_dependents(actor_name)

    def reset_actor(self, actor_name: str) -> bool:
        """
        Returns a tripped actor to service and clears its restart history.

        A tripped breaker is deliberately terminal: the supervisor has no way to
        know whether the cause was fixed, and reclosing it on a timer would turn
        one crash loop into an endless one. Recovery is therefore an explicit
        decision — made by an operator who repaired the dependency, or by a
        control loop that can observe the repair — rather than something that
        happens on its own.

        Clearing the history as well matters: leaving it in place means the next
        single crash re-trips the breaker immediately, so the actor would come
        back with no restart budget at all.

        Returns True if the actor was reset, False if it was not registered.
        """
        with self._lock:
            if actor_name not in self._specs:
                return False
            self._status[actor_name] = "RUNNING"
            self._restart_history[actor_name] = []
            return True

    def _restart_dependents(self, actor_name: str):
        """REST_FOR_ONE: also restart actors that depend on the crashed actor."""
        for name, spec in self._specs.items():
            if name == actor_name:
                continue
            if actor_name in spec.depends_on:
                self._restart_history[name] = []
                self._status[name] = "RESTARTING"

    def get_status(self) -> Dict[str, Any]:
        """Returns the health status of all supervised actors."""
        with self._lock:
            return {
                "strategy": self.strategy,
                "actors_total": len(self._specs),
                "actors_running": sum(1 for s in self._status.values() if s == "RUNNING"),
                "actors_restarting": sum(1 for s in self._status.values() if s == "RESTARTING"),
                "actors_failed": sum(1 for s in self._status.values() if s == "FAILED"),
                "actors_tripped": sum(1 for s in self._status.values() if s == "TRIPPED"),
                "status_map": dict(self._status),
            }
