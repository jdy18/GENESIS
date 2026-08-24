"""Tool interfaces — the seam between the workflow and everything it retrieves.

The workflow depends only on the `Protocol`s below. Anything satisfying them can
be plugged in: a full local retrieval stack, a single flat JSON file, an
in-memory stub for tests. Nothing in `genesis/` imports an HTTP client, a
tool-server SDK or an ontology file.

`Protocol` (structural typing) rather than an abstract base class, so an adopter
does not have to import or subclass anything to be compatible.

Every method is `async`: the three evidence pathways run concurrently. A
synchronous backend can wrap itself with `asyncio.to_thread`.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..types import Candidate, Evidence, Phenotype


@runtime_checkable
class PhenotypeExtractor(Protocol):
    """Free text -> normalized findings.

    Implementations should emit `Phenotype(present=False)` for pertinent
    negatives rather than dropping them — an explicitly absent finding is what
    refutes a candidate later. Temporal information is worth keeping in the
    finding name where the record gives it.
    """

    async def extract(self, text: str) -> list[Phenotype]:
        ...


@runtime_checkable
class ConceptNormalizer(Protocol):
    """Disease name -> ontology ids, so that labels naming the same entity can
    be consolidated before comparison across methods.

    Returns a mapping like `{"MONDO": "0018150", "OMIM": "230800"}`. Returning
    `{}` is legitimate and must not break the workflow — plenty of real
    candidate strings do not resolve, and `Candidate.key()` falls back to the
    name.
    """

    async def normalize(self, names: list[str]) -> list[dict[str, str]]:
        ...


@runtime_checkable
class ExpertMethod(Protocol):
    """One independent diagnostic method used by the consensus agent.

    A phenotype-ranking service, a case-matching service or another model can
    all serve as one: the agent only needs a ranked list back.

    `name` appears verbatim in the consensus evidence and ends up in the
    provenance chain, so keep it stable.
    """

    name: str

    async def rank(
        self, phenotypes: list[Phenotype], text: str | None = None
    ) -> list[Candidate]:
        ...


@runtime_checkable
class KnowledgeSource(Protocol):
    """One queryable knowledge index for the retrieval-and-deduction agent.

    One index — an ontology, a disease knowledge base, a literature corpus.
    `query` is a keyword or natural-language query the agent builds along one of
    three diagnostic axes: defining features, contradictory findings, or
    mechanism.

    `top_k` is per call because the retrieval budget widens when a case enters
    revision.
    """

    name: str

    async def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class CaseIndex(Protocol):
    """Historical-case retrieval for the analogy agent.

    Three representations are offered — a phenotype term set, the free-text
    narrative, and candidate disease names — and an implementation may use
    whichever it supports.
    """

    name: str

    async def search(
        self,
        phenotypes: list[Phenotype],
        text: str | None = None,
        disease_names: list[str] | None = None,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class EvidenceSummarizer(Protocol):
    """Condenses a retrieved record into an `Evidence` with an explicit stance.

    Optional. Leaving it unset passes retrieved records through verbatim, which
    is the preferred mode — a condensed record carries strictly less than the
    record, and condensing is one more place for a model to introduce a disease
    name that was not in the source.

    Where one is used, it must state only what the record says. Fabricated
    supporting evidence is worse than no evidence, because the audit treats it
    as real.
    """

    async def summarize(
        self,
        candidate: Candidate,
        record: dict[str, Any],
        kind: Any,
        source: str,
    ) -> Evidence | None:
        ...
