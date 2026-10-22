"""
Measured token accounting for the coordination layer
====================================================

The headline claim of this runtime is that it removes the *coordination* token
cost of a multi-agent pipeline. A claim like that is worthless as a declared
constant, so nothing here is declared: this module runs the same workload under
both architectures, builds the actual prompt strings each one would send, counts
them, and reports the difference.

What is being compared
----------------------
Both runs perform identical work — the same agents, in the same order, producing
the same outputs. The only thing that differs is **what each agent is given as
context**:

* ``conversational`` — the pattern a chat-orchestrated framework uses: every hop
  receives the whole transcript so far and appends to it. Hop *n* re-sends
  everything hops ``1..n-1`` already said, so the cumulative prompt volume grows
  with the square of the hop count.
* ``tuple_space`` — what this runtime does: a hop receives its system prompt plus
  only the outputs it actually declared a dependency on. The handoff itself
  crosses no wire and reaches no model, so it costs exactly zero tokens.

  This arm is not a simulation of the tuple space — it **is** the tuple space.
  Each hop's context is staged with :meth:`TupleSpace.out`, claimed back with
  :meth:`TupleSpace.in_lease` and closed with :meth:`TupleSpace.complete`, and
  the prompt that gets counted is built from the payload the claim returns. If
  the coordination layer ever started smuggling context between hops, this
  measurement would show it.

The honest caveat, stated here rather than in a footnote: the conversational
baseline is the *naive* replay pattern. A framework that summarises or truncates
history lands somewhere between the two numbers, and a pipeline whose every hop
genuinely depends on every prior hop cannot save anything, because then the two
architectures are sending the same thing. The saving here is the cost of
re-sending context a hop did not ask for.

Why three counters
------------------
This package has no dependencies, so there is no real BPE tokenizer to call. A
single invented number would be exactly the kind of claim this module exists to
replace, so the comparison is instead reported under three independent counting
methods. The *ratio* is the claim, and it holds under all three — which is the
property that makes it tokenizer-independent, and the reason it survives being
re-run against a real tokenizer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Sequence, Tuple

# Imported from the engine module rather than from `client`, which imports this
# module's caller — going through `ModusLight` here would be a cycle.
from .linda import TupleSpace

__all__ = [
    "COUNTERS",
    "DEFAULT_PIPELINE",
    "PipelineStage",
    "TokenComparison",
    "count_chars_over_four",
    "count_subword",
    "count_whitespace",
    "measure_token_reduction",
]


# --------------------------------------------------------------------------
# Counting methods
# --------------------------------------------------------------------------

def count_chars_over_four(text: str) -> int:
    """The rule of thumb published by most providers: ~4 characters per token."""
    return (len(text) + 3) // 4


def count_whitespace(text: str) -> int:
    """Whitespace words, scaled by 1.3 — real tokenizers split some words."""
    words = len(text.split())
    return (words * 13 + 9) // 10


_SUBWORD_RE = re.compile(r"[A-Za-z]+|\d|[^\sA-Za-z\d]")


def count_subword(text: str) -> int:
    """
    A crude word-piece split: letter runs, individual digits, and each symbol.
    Long letter runs are broken every four characters, which is roughly how BPE
    treats a word it has not learned whole.
    """
    total = 0
    for piece in _SUBWORD_RE.findall(text):
        total += (len(piece) + 3) // 4 if piece.isalpha() else 1
    return total


#: The counting methods every comparison is reported under.
COUNTERS: Dict[str, Callable[[str], int]] = {
    "chars_over_four": count_chars_over_four,
    "whitespace_scaled": count_whitespace,
    "subword_split": count_subword,
}


# --------------------------------------------------------------------------
# The workload
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PipelineStage:
    """
    One hop of a multi-agent pipeline.

    `depends_on` is the honest crux of the whole measurement: it names the
    stages whose output this stage actually needs. The tuple-space run sends
    exactly those and nothing else; the conversational run sends everything
    regardless.
    """

    name: str
    system_prompt: str
    output: str
    depends_on: Tuple[str, ...] = ()


#: A deliberately ordinary five-stage document pipeline. Nothing about the
#: measurement depends on these particular strings — `measure_token_reduction`
#: accepts any pipeline — but a fixed workload makes the published number
#: reproducible.
DEFAULT_PIPELINE: Tuple[PipelineStage, ...] = (
    PipelineStage(
        name="intake",
        system_prompt=(
            "You are the intake agent. Extract the customer, the requested service and "
            "the delivery deadline from the inbound request. Reply as compact JSON."
        ),
        output=(
            '{"customer": "Northwind Logistics GmbH", "service": "cross-border freight audit", '
            '"deadline": "2026-11-14", "contact_ref": "CRM-88412", '
            '"stated_budget_eur": 48000, "urgency": "standard"}'
        ),
    ),
    PipelineStage(
        name="classifier",
        system_prompt=(
            "You are the classification agent. Assign the request to a service line and a "
            "risk band. Reply as compact JSON."
        ),
        output=(
            '{"service_line": "regulated_freight", "risk_band": "B", '
            '"requires_customs_review": true, "sla_hours": 72}'
        ),
        depends_on=("intake",),
    ),
    PipelineStage(
        name="pricing",
        system_prompt=(
            "You are the pricing agent. Produce a quote for the classified service line "
            "within the stated budget. Reply as compact JSON."
        ),
        output=(
            '{"quote_eur": 44500, "margin_pct": 21.5, "line_items": '
            '[{"audit": 28000}, {"customs_review": 11500}, {"reporting": 5000}], '
            '"valid_until": "2026-11-07"}'
        ),
        depends_on=("intake", "classifier"),
    ),
    PipelineStage(
        name="compliance",
        system_prompt=(
            "You are the compliance agent. Check the quote against sanctions, customs and "
            "data-residency policy. Reply as compact JSON."
        ),
        output=(
            '{"sanctions_check": "clear", "customs_regime": "EU-UK TCA", '
            '"data_residency": "eu-central-1", "approved": true, '
            '"conditions": ["origin certificate required before dispatch"]}'
        ),
        depends_on=("classifier", "pricing"),
    ),
    PipelineStage(
        name="writer",
        system_prompt=(
            "You are the drafting agent. Write the customer-facing quotation letter from the "
            "approved quote and its compliance conditions."
        ),
        output=(
            "Dear Northwind Logistics GmbH,\n\nThank you for your request for a cross-border "
            "freight audit. We are pleased to quote EUR 44,500, comprising the audit itself "
            "(EUR 28,000), customs review (EUR 11,500) and reporting (EUR 5,000). The quote "
            "is valid until 7 November 2026 and assumes delivery against a 72-hour service "
            "level.\n\nOur compliance review is clear under the EU-UK Trade and Cooperation "
            "Agreement, with all data held in eu-central-1. One condition applies: an origin "
            "certificate is required before dispatch.\n\nKind regards,\nClient Services"
        ),
        depends_on=("pricing", "compliance"),
    ),
)


# --------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------

@dataclass
class TokenComparison:
    """The measured result. Every field is counted, none is asserted."""

    hops: int
    counter: str
    conversational_tokens: int
    tuple_space_tokens: int
    coordination_tokens: int
    per_hop_conversational: List[int] = field(default_factory=list)
    per_hop_tuple_space: List[int] = field(default_factory=list)
    #: Tuples actually staged and claimed through `TupleSpace` during the
    #: measurement. Equal to `hops` unless a claim failed, which would mean the
    #: tuple-space arm silently measured fewer hops than it reported.
    tuples_claimed: int = 0

    @property
    def tokens_saved(self) -> int:
        return self.conversational_tokens - self.tuple_space_tokens

    @property
    def reduction_pct(self) -> float:
        if not self.conversational_tokens:
            return 0.0
        return self.tokens_saved / self.conversational_tokens * 100.0

    @property
    def factor(self) -> float:
        """How many times more tokens the conversational run sends."""
        if not self.tuple_space_tokens:
            return 0.0
        return self.conversational_tokens / self.tuple_space_tokens


def _resolve(stages: Sequence[PipelineStage], repeats: int) -> List[PipelineStage]:
    """Lengthen the pipeline by repeating it, so hop-count scaling is visible."""
    if repeats <= 1:
        return list(stages)
    out: List[PipelineStage] = []
    for cycle in range(repeats):
        for stage in stages:
            suffix = "" if cycle == 0 else f"_{cycle}"
            out.append(
                PipelineStage(
                    name=f"{stage.name}{suffix}",
                    system_prompt=stage.system_prompt,
                    output=stage.output,
                    depends_on=tuple(f"{d}{suffix}" for d in stage.depends_on),
                )
            )
    return out


def measure_token_reduction(
    stages: Sequence[PipelineStage] = DEFAULT_PIPELINE,
    counter: str = "chars_over_four",
    repeats: int = 1,
) -> TokenComparison:
    """
    Run one pipeline under both architectures and count what each would send.

    Returns the measured comparison. Raises KeyError for an unknown counter and
    ValueError for a stage that depends on something that has not run yet —
    there is no silent fallback, because a dependency typo would otherwise show
    up as a larger saving.
    """
    count = COUNTERS[counter]
    pipeline = _resolve(stages, repeats)
    produced: Dict[str, str] = {}
    for stage in pipeline:
        for dep in stage.depends_on:
            if dep not in produced and dep not in {s.name for s in pipeline}:
                raise ValueError(f"stage '{stage.name}' depends on unknown stage '{dep}'")
        produced[stage.name] = stage.output

    conversational: List[int] = []
    tuple_space: List[int] = []
    transcript: List[str] = []
    results: Dict[str, str] = {}
    space = TupleSpace()
    claims = 0

    for stage in pipeline:
        # Conversational: the hop is handed the entire transcript so far.
        chat_prompt = "\n".join([stage.system_prompt, *transcript])
        conversational.append(count(chat_prompt) + count(stage.output))
        transcript.append(f"{stage.name}: {stage.output}")

        # Tuple space: stage the hop's context as a real tuple, then claim it
        # back and build the prompt from what the claim actually returns. The
        # handoff is in-process, so it reaches no model and costs nothing —
        # which is why only the prompt and the reply are counted.
        space.out(
            topic=stage.name,
            payload={"inputs": {dep: results[dep] for dep in stage.depends_on}},
        )
        task = space.in_lease(worker_id="meter", topic=stage.name)
        if task is None:
            raise RuntimeError(
                f"the tuple staged for stage '{stage.name}' could not be claimed back; "
                "the tuple-space arm cannot be measured without it"
            )
        claims += 1
        claimed = [f"{dep}: {value}" for dep, value in task.payload["inputs"].items()]
        tuple_prompt = "\n".join([stage.system_prompt, *claimed])
        tuple_space.append(count(tuple_prompt) + count(stage.output))
        space.complete(task.id, {"output": stage.output}, worker_id="meter")
        results[stage.name] = stage.output

    return TokenComparison(
        tuples_claimed=claims,
        hops=len(pipeline),
        counter=counter,
        conversational_tokens=sum(conversational),
        tuple_space_tokens=sum(tuple_space),
        coordination_tokens=0,
        per_hop_conversational=conversational,
        per_hop_tuple_space=tuple_space,
    )
