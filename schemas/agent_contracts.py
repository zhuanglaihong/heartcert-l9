"""
Task 2 — Agent I/O Pydantic Contracts
覆盖 4 个 Agent 的强类型输入输出定义
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


# ─── Ingestion Agent ──────────────────────────────────────────────────────────

class AbilityEvidence(BaseModel):
    atom_id: int = Field(..., ge=1, le=1024)
    evidence_quote: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)


class CandidateDNA(BaseModel):
    candidate_id: str
    role: str
    raw_abilities: list[AbilityEvidence]
    missing_areas: list[int] = Field(default_factory=list)
    dominant_language: str | None = None
    years_of_relevant_exp: int | None = None
    dna_version: str = "1.0"

    @field_validator("missing_areas")
    @classmethod
    def validate_missing_atom_ids(cls, v: list[int]) -> list[int]:
        for atom_id in v:
            if not (1 <= atom_id <= 1024):
                raise ValueError(f"missing_areas contains out-of-range atom_id: {atom_id}")
        return v


# ─── Battlefield Agent ────────────────────────────────────────────────────────

class CodeFile(BaseModel):
    filename: str
    content: str


class TestCase(BaseModel):
    name: str
    trigger_condition: str
    expected_failure: str


class BugLocation(BaseModel):
    file: str
    function: str
    line_hint_for_judge_only: int


class FakeDocs(BaseModel):
    quickstart: str
    api_reference: str
    config_guide: str


class FallbackBlueprint(BaseModel):
    framework_name: str
    language: str
    bug_type: str
    code_artifact: dict


class BattlefieldBlueprint(BaseModel):
    blueprint_id: str
    framework_name: str
    framework_version: str
    language: str
    bug_type: Literal["deadlock", "goroutine_leak", "connection_exhaustion", "race_condition"]
    bug_location: BugLocation
    code_artifact: dict
    fake_docs: FakeDocs
    fallback_blueprint: FallbackBlueprint
    difficulty_rating: int = Field(..., ge=1, le=5)


# ─── X-RAG Agent ─────────────────────────────────────────────────────────────

class AttackVector(BaseModel):
    simulated_failure: str
    target_file: str
    target_function: str


class XRAGChallenge(BaseModel):
    action: Literal["INJECT", "NO_TRIGGER"]
    # NO_TRIGGER fields
    reason: str | None = None
    # INJECT fields
    challenge_id: str | None = None
    trigger_reason: str | None = None
    attack_vector: AttackVector | None = None
    modal_question: str | None = None
    expected_defense: str | None = None
    difficulty_delta: int | None = Field(None, ge=-2, le=2)


# ─── Oracle Judge Agent ───────────────────────────────────────────────────────

class VectorUpdate(BaseModel):
    atom_id: int = Field(..., ge=1, le=1024)
    score: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., min_length=10)

    @field_validator("score")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(v, 2)


class JudgeResult(BaseModel):
    vector_updates: list[VectorUpdate]
    verified_skills: list[str]
    reranker_payload: str = Field(..., max_length=900)  # ~150 words
    combat_confidence: float = Field(..., ge=0.0, le=1.0)
    unassessed_atom_ids: list[int] = Field(default_factory=list)

    @field_validator("vector_updates")
    @classmethod
    def no_duplicate_atom_ids(cls, v: list[VectorUpdate]) -> list[VectorUpdate]:
        seen = set()
        for upd in v:
            if upd.atom_id in seen:
                raise ValueError(f"Duplicate atom_id in vector_updates: {upd.atom_id}")
            seen.add(upd.atom_id)
        return v
