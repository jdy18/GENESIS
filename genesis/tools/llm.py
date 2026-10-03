"""Auxiliary language-model adapters for phenotype and record processing."""
from __future__ import annotations

import json

from ..llm.base import ChatModel, parse_json
from ..prompts import PHENOTYPE_EXTRACTION, RECORD_CONDENSATION
from ..types import Candidate, Evidence, EvidenceKind, Phenotype, Stance


class ModelPhenotypeExtractor:
    """Extract findings and explicit negatives; ontology mapping stays in tools.

    The prompt returns finding text and source spans, not invented HPO IDs.
    A configured ontology encoder can subsequently ground these findings.
    """

    def __init__(self, model: ChatModel) -> None:
        self.model = model

    @property
    def requires_external_access(self) -> bool | None:
        return getattr(self.model, "requires_external_access", None)

    async def extract(self, text: str) -> list[Phenotype]:
        obj = parse_json(await self.model.chat(
            PHENOTYPE_EXTRACTION,
            json.dumps({"clinical_case": text}, ensure_ascii=False),
            temperature=0.0,
        ))
        if not isinstance(obj, dict) or not isinstance(obj.get("findings"), list):
            raise ValueError("phenotype extraction returned no findings list")
        findings = []
        for item in obj["findings"]:
            if not isinstance(item, dict):
                continue
            name, present = item.get("name"), item.get("present")
            if not isinstance(name, str) or not name.strip() or not isinstance(present, bool):
                continue
            span = item.get("source_span")
            if not isinstance(span, str) or not span or span not in text:
                continue
            findings.append(Phenotype(name.strip(), present=present, source_span=span))
        return findings


class ModelEvidenceSummarizer:
    """Use the auxiliary model to extract relevant passages from a record.

    The source record remains in `raw`; its stable identifier and score are
    carried forward. Malformed replies raise so retrieval can retain the record.
    """

    def __init__(self, model: ChatModel) -> None:
        self.model = model

    @property
    def requires_external_access(self) -> bool | None:
        return getattr(self.model, "requires_external_access", None)

    async def summarize(
        self, candidate: Candidate, record: dict, kind: EvidenceKind, source: str,
    ) -> Evidence:
        obj = parse_json(await self.model.chat(
            RECORD_CONDENSATION,
            json.dumps({"candidate": candidate.name, "retrieved_record": record},
                       ensure_ascii=False, default=str),
            temperature=0.0,
        ))
        if not isinstance(obj, dict) or not isinstance(obj.get("summary"), str):
            raise ValueError("record processing returned no summary")
        summary = obj["summary"].strip()
        if not summary:
            raise ValueError("record processing returned an empty summary")
        try:
            stance = Stance(obj.get("stance"))
        except (ValueError, TypeError):
            raise ValueError("record processing returned an invalid stance") from None
        source_id = next((str(record[k]) for k in
                          ("pmid", "id", "omim_id", "orpha_id", "hpo_id", "doc_id")
                          if record.get(k)), None)
        score = next((float(record[k]) for k in
                      ("score", "rerank_score", "relevance", "similarity")
                      if isinstance(record.get(k), (int, float))), None)
        return Evidence(candidate.key(), kind, stance, source, content=summary,
                        source_id=source_id, score=score, raw=record)
