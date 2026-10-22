"""
Tests for Modus Light Linda Tuple Space
"""

import unittest
from modus_light.linda import TupleSpace


class TestTupleSpace(unittest.TestCase):

    def setUp(self):
        self.space = TupleSpace()

    def test_out_and_rd(self):
        t1 = self.space.out("orders", {"item": "widget", "qty": 5}, priority=1)
        self.assertEqual(t1.status, "PENDING")

        # Read without claiming
        read_t = self.space.rd(topic="orders")
        self.assertIsNotNone(read_t)
        self.assertEqual(read_t.id, t1.id)
        self.assertEqual(read_t.status, "PENDING")

    def test_in_lease_and_complete(self):
        t = self.space.out("jobs", {"job_id": 99}, priority=5)
        claimed = self.space.in_lease(worker_id="agent_01", topic="jobs")

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, t.id)
        self.assertEqual(claimed.status, "LEASED")
        self.assertEqual(claimed.lease_owner, "agent_01")

        # Complete
        self.assertTrue(self.space.complete(claimed.id, {"exit_code": 0}, worker_id="agent_01"))
        # Now no pending jobs should be claimable
        second_claim = self.space.in_lease(worker_id="agent_02", topic="jobs")
        self.assertIsNone(second_claim)

    def test_priority_ordering(self):
        self.space.out("tasks", {"task": "low"}, priority=1)
        self.space.out("tasks", {"task": "critical"}, priority=100)
        self.space.out("tasks", {"task": "medium"}, priority=10)

        # First in_lease must return critical
        first = self.space.in_lease(worker_id="w1", topic="tasks")
        self.assertEqual(first.payload["task"], "critical")

        # Second in_lease must return medium
        second = self.space.in_lease(worker_id="w2", topic="tasks")
        self.assertEqual(second.payload["task"], "medium")

    def test_complete_rejects_an_unleased_tuple(self):
        """An 'exclusive lease' means work cannot be closed out before it is claimed."""
        t = self.space.out("jobs", {"job_id": 1})
        self.assertFalse(self.space.complete(t.id, worker_id="nobody"))
        self.assertEqual(self.space.count(status="PENDING"), 1)

    def test_complete_rejects_a_foreign_worker(self):
        """Worker B must not be able to close out the task Worker A holds."""
        self.space.out("jobs", {"job_id": 2})
        claimed = self.space.in_lease(worker_id="agent_a", topic="jobs")

        self.assertFalse(self.space.complete(claimed.id, worker_id="agent_b"))
        self.assertEqual(claimed.status, "LEASED")

        # The rightful holder still succeeds.
        self.assertTrue(self.space.complete(claimed.id, worker_id="agent_a"))

    def test_complete_is_not_idempotent(self):
        """A second completion must fail, so a duplicate result cannot overwrite the first."""
        self.space.out("jobs", {"job_id": 3})
        claimed = self.space.in_lease(worker_id="agent_a", topic="jobs")

        self.assertTrue(self.space.complete(claimed.id, {"exit_code": 0}, worker_id="agent_a"))
        self.assertFalse(self.space.complete(claimed.id, {"exit_code": 1}, worker_id="agent_a"))
        self.assertEqual(claimed.payload["_result"], {"exit_code": 0})

    def test_completed_tuples_are_evicted_once_retention_is_exceeded(self):
        """Completed tuples must be bounded: a long-running coordinator that
        keeps every task it ever ran grows without limit."""
        space = TupleSpace(completed_retention=5)
        for i in range(50):
            space.out("jobs", {"n": i})
            claimed = space.in_lease(worker_id="w", topic="jobs")
            self.assertTrue(space.complete(claimed.id, worker_id="w"))

        self.assertEqual(space.count(status="COMPLETED"), 5)
        self.assertEqual(space.count(), 5)

    def test_zero_retention_discards_results_immediately(self):
        space = TupleSpace(completed_retention=0)
        space.out("jobs", {"n": 1})
        claimed = space.in_lease(worker_id="w", topic="jobs")

        self.assertTrue(space.complete(claimed.id, worker_id="w"))
        self.assertEqual(space.count(), 0)


if __name__ == "__main__":
    unittest.main()
