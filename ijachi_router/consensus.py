"""Multi-Model Consensus & Peer Review Engine for ijachi-code.

Queries 2 top frontier models independently and peer-reviews their solutions
to eliminate single-model hallucinations.
"""

from __future__ import annotations

from dataclasses import dataclass
from ijachi_router.core import route
from ijachi_router.providers.base import GenerationResult


@dataclass
class ConsensusResult:
    final_text: str
    model_a: str
    model_b: str
    response_a: str
    response_b: str
    total_cost_usd: float
    consensus_model: str


def consensus_route(prompt: str, priority: str = "quality") -> ConsensusResult:
    """Query 2 frontier models independently and generate a peer-reviewed consensus output."""
    # First candidate call
    res1 = route(prompt=prompt, priority=priority)

    # Second candidate call with speed/alternative priority bias
    alt_priority = "cost" if priority == "quality" else "quality"
    res2 = route(prompt=prompt, priority=alt_priority)

    total_cost = res1.cost_usd + res2.cost_usd

    # If same model was picked twice or outputs are identical, return first
    if res1.model == res2.model or res1.text.strip() == res2.text.strip():
        return ConsensusResult(
            final_text=res1.text,
            model_a=res1.model,
            model_b=res2.model,
            response_a=res1.text,
            response_b=res2.text,
            total_cost_usd=total_cost,
            consensus_model=res1.model,
        )

    # Peer review synthesis prompt
    synthesis_prompt = (
        f"You are a Senior Software Architect acting as a Peer Reviewer.\n\n"
        f"Original Prompt: {prompt}\n\n"
        f"Candidate Solution A (from {res1.model}):\n{res1.text}\n\n"
        f"Candidate Solution B (from {res2.model}):\n{res2.text}\n\n"
        f"Analyze both solutions, pick the best parts of each, correct any bugs, "
        f"and output the single definitive, production-ready response."
    )

    synthesis_res = route(prompt=synthesis_prompt, priority="quality")
    total_cost += synthesis_res.cost_usd

    return ConsensusResult(
        final_text=synthesis_res.text,
        model_a=res1.model,
        model_b=res2.model,
        response_a=res1.text,
        response_b=res2.text,
        total_cost_usd=total_cost,
        consensus_model=synthesis_res.model,
    )
