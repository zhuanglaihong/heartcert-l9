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
    # char_offset_in_resume enables code-level verification: resume_text[offset:offset+len(quote)] == quote
    char_offset_in_resume: int | None = Field(None, ge=0)
    # reasoning_trace: ≤200-char judgment chain for audit (why this atom_id was assigned)
    reasoning_trace: str | None = Field(None, max_length=200)
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


class BattlefieldAudit(BaseModel):
    # Internal-only: must NOT be surfaced to the candidate frontend
    bug_location: BugLocation
    # At least 3 concrete discrepancies between fake_docs and actual code behavior
    docs_diff: list[str] = Field(..., min_length=3)


class BattlefieldBlueprint(BaseModel):
    blueprint_id: str
    framework_name: str
    framework_version: str
    language: str
    bug_type: Literal["deadlock", "goroutine_leak", "connection_exhaustion", "race_condition"]
    # Atom IDs this blueprint exercises — used by Oracle Judge for alignment
    target_atom_ids: list[int] = Field(..., min_length=1, max_length=5)
    code_artifact: dict
    fake_docs: FakeDocs
    fallback_blueprint: FallbackBlueprint
    difficulty_rating: int = Field(..., ge=1, le=5)
    # audit is internal-only; replaces top-level bug_location from old schema
    audit: BattlefieldAudit

    @field_validator("target_atom_ids")
    @classmethod
    def validate_target_atom_ids(cls, v: list[int]) -> list[int]:
        for aid in v:
            if not (1 <= aid <= 1024):
                raise ValueError(f"target_atom_ids contains out-of-range atom_id: {aid}")
        return v


# ─── X-RAG Agent ─────────────────────────────────────────────────────────────

class AttackVector(BaseModel):
    simulated_failure: str
    target_file: str
    target_function: str


class XRAGChallenge(BaseModel):
    action: Literal["INJECT", "NO_TRIGGER"]
    # track routes to the correct scoring rubric: code track vs product/architecture track
    track: Literal["code", "prd"] | None = None
    # NO_TRIGGER fields
    reason: str | None = None
    # INJECT fields
    challenge_id: str | None = None
    trigger_reason: str | None = None
    attack_vector: AttackVector | None = None
    # max_length=200 enforces single-screen readability in the modal dialog
    modal_question: str | None = Field(None, max_length=200)
    expected_defense: str | None = None
    difficulty_delta: int | None = Field(None, ge=-2, le=2)


# ─── Oracle Judge Agent ───────────────────────────────────────────────────────

class VectorUpdate(BaseModel):
    # Sparse entry for the ability ledger (question_ability_scores table)
    # Expected rationale format: "event#N [t=Ts]: <≤80-char fact referencing battle_log>"
    atom_id: int = Field(..., ge=1, le=1024)
    score: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., min_length=10)

    @field_validator("score")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(v, 2)


class JudgeResult(BaseModel):
    # Sparse ledger entries — used for detail pages and question_ability_scores writes
    vector_updates: list[VectorUpdate]
    # Dense 1024D ability vector for HNSW ANN recall (candidate_vectors.ability_vec_1024)
    # Smoothing rules: assessed→actual score, resume-claimed→smoothing_baseline, else→0.0
    dense_vector_1024: list[float] | None = None
    # Baseline weight for resume-claimed but unassessed abilities (avoids sparsity curse)
    smoothing_baseline: float = Field(0.02, ge=0.0, le=0.1)
    verified_skills: list[str]
    reranker_payload: str = Field(..., max_length=900)  # ~150 words
    combat_confidence: float = Field(..., ge=0.0, le=1.0)
    unassessed_atom_ids: list[int] = Field(default_factory=list)
    # ISO8601 timestamp — required for B-end time-decay ranking factor
    last_certified_at: str | None = None
    # Human-readable log of smoothing decisions for audit (≤500 chars)
    vector_construction_log: str | None = Field(None, max_length=500)

    @field_validator("vector_updates")
    @classmethod
    def no_duplicate_atom_ids(cls, v: list[VectorUpdate]) -> list[VectorUpdate]:
        seen = set()
        for upd in v:
            if upd.atom_id in seen:
                raise ValueError(f"Duplicate atom_id in vector_updates: {upd.atom_id}")
            seen.add(upd.atom_id)
        return v

    @field_validator("dense_vector_1024")
    @classmethod
    def validate_dense_vector(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return v
        if len(v) != 1024:
            raise ValueError(f"dense_vector_1024 must have exactly 1024 elements, got {len(v)}")
        for x in v:
            if not (0.0 <= x <= 1.0):
                raise ValueError(f"dense_vector_1024 contains out-of-range value: {x}")
        return v
