"""
Capability Profiles (Day-3 sl.41).

A capability profile is a swappable, version-controlled bundle of {model, token caps,
thinking budget, allowed tools, context policy} for one DAG node. Because each node
runs as its own stateless model call (the API has no persistent agent memory), context
isolation is achieved by construction: a node only ever sees the inputs the DAG hands
it, never another node's scratch context. "memory purge" here means "fresh call",
stated honestly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class CapabilityProfile:
    name: str
    model_role: str            # which config model to use: business|curation|source|cheap
    max_tokens: int = 4000
    thinking_budget: int = 0
    allowed_tools: List[str] = field(default_factory=list)
    context_policy: str = "isolated"   # documents that nodes don't share scratch context
    version: str = "1.0.0"


# the project's profiles, in one place so they can be reviewed/pinned like dependencies
PROFILES = {
    "source": CapabilityProfile(
        name="source-processing", model_role="source", max_tokens=1200,
        allowed_tools=["read_bus_record", "read_reference"], version="1.1.0",
    ),
    "curation": CapabilityProfile(
        name="curation", model_role="curation", max_tokens=3000, version="1.1.0",
    ),
    "business": CapabilityProfile(
        name="business", model_role="business", max_tokens=8000, thinking_budget=4000,
        version="1.1.0",
    ),
    "judge": CapabilityProfile(
        name="judge", model_role="cheap", max_tokens=200, version="1.1.0",
    ),
}
