#!/usr/bin/env python3
"""
Example 04: Erlang OTP Supervisor & Circuit Breaker Dampening
============================================================
Demonstrates actor isolation, self-healing process restarts, and
automatic circuit breaker dampening when an actor crashes repeatedly.
"""
import sys
from pathlib import Path

# Add src to sys.path so examples run immediately without prior pip install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# The status glyphs below are non-ASCII. On a stream that cannot encode them —
# cp1252 on Windows when output is redirected to a file, or an explicit
# PYTHONIOENCODING=ascii — printing would raise UnicodeEncodeError and lose the
# exit status. Degrade the glyph instead of failing the run.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from modus_light import ModusLight, ActorSpec, ActorCrashError, CircuitBreakerTrippedError


def main():
    rt = ModusLight()

    crash_count = 0

    def unstable_worker(task_id: int):
        nonlocal crash_count
        crash_count += 1
        if crash_count < 3:
            raise ConnectionResetError(f"Network drop on task {task_id}")
        return f"Task {task_id} successfully processed after recovery!"

    # Register worker with supervisor (max 3 restarts within 5 seconds)
    spec = ActorSpec(name="sync_worker", role="network_client", max_restarts=3, restart_window_seconds=5.0)
    rt.supervisor.register_actor(spec, unstable_worker)

    print("Executing unstable worker under Erlang OTP supervision...")
    for i in range(1, 3):
        try:
            rt.supervisor.execute_actor("sync_worker", task_id=i)
        except ActorCrashError as err:
            print(f"  [Attempt {i}] Worker panic isolated by supervisor: {err}")

    # On third attempt, worker recovers
    res = rt.supervisor.execute_actor("sync_worker", task_id=3)
    print(f"✓ Recovered: {res}")

    # Now simulate a catastrophic permanent loop crash

    def fatal_worker():
        raise RuntimeError("Fatal memory corruptor")

    fatal_spec = ActorSpec(name="fatal_agent", role="faulty", max_restarts=3, restart_window_seconds=10.0)
    rt.supervisor.register_actor(fatal_spec, fatal_worker)

    print("\nSimulating repeated crash loop on 'fatal_agent' to test circuit breaker...")
    for i in range(4):
        try:
            rt.supervisor.execute_actor("fatal_agent")
        except ActorCrashError:
            print(f"  Isolated crash {i+1}...")
        except CircuitBreakerTrippedError as err:
            print("✓ Circuit Breaker Tripped! System halted recursive crash loops:")
            print(f"  --> {err}")
            break

    print("\nSupervisor Health Status:", rt.supervisor.get_status())


if __name__ == "__main__":
    main()
