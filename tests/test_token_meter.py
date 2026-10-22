"""
Tests for the measured token-reduction claim
============================================

The token saving is the single most load-bearing claim this project makes, so
these tests exist to keep it a measurement rather than a stated constant: that
the numbers are produced by counting real prompts, that the mechanism is the one
advertised, and — most importantly — that the measurement is capable of
reporting *no* saving when none is available.
"""

import unittest

from modus_light.token_meter import (
    COUNTERS,
    DEFAULT_PIPELINE,
    PipelineStage,
    measure_token_reduction,
)


class TestTheMeasurementIsHonest(unittest.TestCase):
    """A measurement that can only ever return good news is not a measurement."""

    def test_a_pipeline_where_every_hop_needs_everything_saves_nothing(self):
        """
        The saving comes from *not re-sending context a hop did not ask for*. If
        every hop genuinely depends on every prior hop, the two architectures
        send the same thing and the honest answer is zero. This is the test that
        proves the meter is measuring rather than flattering.
        """
        stages = []
        for index in range(8):
            stages.append(
                PipelineStage(
                    name=f"stage_{index}",
                    system_prompt="You are an agent that needs the entire history.",
                    output=f"output of stage {index}, which is a sentence of some length",
                    depends_on=tuple(f"stage_{j}" for j in range(index)),
                )
            )
        result = measure_token_reduction(stages)
        self.assertEqual(
            result.tokens_saved, 0,
            "a fully-dependent pipeline must report no saving, not a positive one",
        )
        self.assertEqual(result.reduction_pct, 0.0)

    def test_a_single_hop_pipeline_saves_nothing(self):
        """With one hop there is no history to replay, so there is nothing to win."""
        result = measure_token_reduction(DEFAULT_PIPELINE[:1])
        self.assertEqual(result.tokens_saved, 0)

    def test_the_reduction_is_modest_on_a_short_pipeline(self):
        """
        Published honesty check. The headline figure only appears on long
        pipelines; on the default five-stage one it is small, and the docs say
        so. If this ever starts reporting a large number for five hops, either
        the baseline got unfair or the pipeline changed.
        """
        result = measure_token_reduction()
        self.assertEqual(result.hops, 5)
        self.assertLess(
            result.reduction_pct, 30.0,
            "a 5-hop reduction above 30% means the conversational baseline is inflated",
        )
        self.assertGreater(result.reduction_pct, 5.0)


class TestTheAdvertisedMechanism(unittest.TestCase):

    def test_the_handoff_itself_costs_zero_tokens(self):
        """The central claim: coordination reaches no model, so it bills nothing."""
        self.assertEqual(measure_token_reduction(repeats=10).coordination_tokens, 0)

    def test_the_measurement_runs_through_the_real_tuple_space(self):
        """
        The tuple-space arm would be worthless if it were a string simulation
        of the coordination layer, so it stages and claims a real tuple per hop
        and this asserts every one of them was claimed back.
        """
        for repeats in (1, 4, 20):
            result = measure_token_reduction(repeats=repeats)
            with self.subTest(hops=result.hops):
                self.assertEqual(result.tuples_claimed, result.hops)

    def test_tuple_space_cost_is_linear_in_hop_count(self):
        """A flat per-hop cost is what makes the saving grow without bound."""
        per_hop = []
        for repeats in (2, 4, 10, 20):
            result = measure_token_reduction(repeats=repeats)
            per_hop.append(result.tuple_space_tokens / result.hops)
        self.assertAlmostEqual(min(per_hop), max(per_hop), delta=1.0)

    def test_conversational_cost_grows_faster_than_linearly(self):
        """Doubling the hops must more than double the replayed volume."""
        short = measure_token_reduction(repeats=4)
        long = measure_token_reduction(repeats=8)
        self.assertEqual(long.hops, short.hops * 2)
        self.assertGreater(long.conversational_tokens, short.conversational_tokens * 2.5)

    def test_the_reduction_rises_with_pipeline_length(self):
        values = [measure_token_reduction(repeats=r).reduction_pct for r in (1, 2, 4, 10, 20)]
        self.assertEqual(values, sorted(values))
        self.assertGreater(values[-1], 90.0)


class TestTheResultDoesNotDependOnHowYouCount(unittest.TestCase):
    """Three counters, no tokenizer dependency: the ratio is the claim."""

    def test_every_counter_agrees_on_a_long_pipeline(self):
        for repeats in (4, 10, 20):
            values = [
                measure_token_reduction(counter=name, repeats=repeats).reduction_pct
                for name in COUNTERS
            ]
            with self.subTest(hops=repeats * 5):
                self.assertLess(
                    max(values) - min(values), 1.0,
                    f"counters disagree by {max(values) - min(values):.2f} points",
                )

    def test_every_counter_is_monotonic_in_text_length(self):
        """
        Growth is measured on added *words*, not added characters inside one
        word: `whitespace_scaled` counts word boundaries and is blind to a
        single long token. That is a real limitation of that counter, which is
        why no claim rests on one of them alone.
        """
        for name, counter in COUNTERS.items():
            with self.subTest(counter=name):
                self.assertLess(counter("a short line"), counter("a short line " * 20))
                self.assertEqual(counter(""), 0)

    def test_an_unknown_counter_is_refused_rather_than_defaulted(self):
        with self.assertRaises(KeyError):
            measure_token_reduction(counter="whatever_sounds_best")


class TestTheMeterRefusesBadInput(unittest.TestCase):

    def test_a_dependency_on_a_nonexistent_stage_raises(self):
        """
        Silently ignoring an unresolvable dependency would understate the
        tuple-space cost and overstate the saving, so it fails loudly.
        """
        stages = (
            PipelineStage(name="a", system_prompt="p", output="o"),
            PipelineStage(name="b", system_prompt="p", output="o", depends_on=("typo",)),
        )
        with self.assertRaises(ValueError):
            measure_token_reduction(stages)


if __name__ == "__main__":
    unittest.main()
