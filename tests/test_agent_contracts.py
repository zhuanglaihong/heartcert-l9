"""
Module: schemas/agent_contracts.py
Tests: Pydantic 合约的约束校验（atom_id 范围、重复检测、score 精度）
"""

import pytest
from pydantic import ValidationError
from schemas.agent_contracts import (
    AbilityEvidence,
    CandidateDNA,
    BattlefieldBlueprint,
    XRAGChallenge,
    AttackVector,
    JudgeResult,
    VectorUpdate,
)


# ─── CandidateDNA ─────────────────────────────────────────────────────────────

class TestCandidateDNA:
    def test_valid_dna(self):
        dna = CandidateDNA(
            candidate_id="c-001",
            role="Golang 后端",
            raw_abilities=[
                AbilityEvidence(atom_id=42, evidence_quote="负责 Go 微服务开发", confidence=0.9)
            ],
            missing_areas=[100, 200],
        )
        assert dna.dna_version == "1.0"
        assert len(dna.raw_abilities) == 1

    def test_atom_id_lower_bound(self):
        with pytest.raises(ValidationError):
            AbilityEvidence(atom_id=0, evidence_quote="x", confidence=0.5)

    def test_atom_id_upper_bound(self):
        with pytest.raises(ValidationError):
            AbilityEvidence(atom_id=1025, evidence_quote="x", confidence=0.5)

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            AbilityEvidence(atom_id=1, evidence_quote="x", confidence=1.1)

    def test_missing_areas_invalid_atom_id(self):
        with pytest.raises(ValidationError):
            CandidateDNA(
                candidate_id="c-001",
                role="test",
                raw_abilities=[],
                missing_areas=[0],  # 越界
            )

    def test_empty_evidence_quote_rejected(self):
        with pytest.raises(ValidationError):
            AbilityEvidence(atom_id=1, evidence_quote="", confidence=0.5)


# ─── JudgeResult ─────────────────────────────────────────────────────────────

class TestJudgeResult:
    def _make_update(self, atom_id: int, score: float = 0.8) -> VectorUpdate:
        return VectorUpdate(atom_id=atom_id, score=score, rationale="event#1 [t=120s]: 修复了死锁")

    def test_valid_judge_result(self):
        jr = JudgeResult(
            vector_updates=[self._make_update(42), self._make_update(145)],
            verified_skills=["Golang", "Redis"],
            reranker_payload="候选人在沙盒中完成了分布式锁修复。",
            combat_confidence=0.88,
        )
        assert len(jr.vector_updates) == 2

    def test_duplicate_atom_id_rejected(self):
        with pytest.raises(ValidationError):
            JudgeResult(
                vector_updates=[self._make_update(42), self._make_update(42)],
                verified_skills=[],
                reranker_payload="test",
                combat_confidence=0.5,
            )

    def test_score_rounded_to_two_decimals(self):
        upd = VectorUpdate(atom_id=1, score=0.856789, rationale="event#1 修复完成")
        assert upd.score == 0.86

    def test_reranker_payload_max_length(self):
        with pytest.raises(ValidationError):
            JudgeResult(
                vector_updates=[],
                verified_skills=[],
                reranker_payload="x" * 901,  # 超过 900 字符上限
                combat_confidence=0.5,
            )

    def test_combat_confidence_bounds(self):
        with pytest.raises(ValidationError):
            JudgeResult(
                vector_updates=[],
                verified_skills=[],
                reranker_payload="test",
                combat_confidence=1.1,
            )


# ─── XRAGChallenge ────────────────────────────────────────────────────────────

class TestXRAGChallenge:
    def test_no_trigger(self):
        c = XRAGChallenge(action="NO_TRIGGER", reason="仅格式化修改，不触发")
        assert c.challenge_id is None

    def test_inject_challenge(self):
        c = XRAGChallenge(
            action="INJECT",
            challenge_id="ch-001",
            trigger_reason="test_failure",
            attack_vector=AttackVector(
                simulated_failure="Redis 主节点宕机",
                target_file="lock.go",
                target_function="AcquireLock",
            ),
            modal_question="Redis 主节点宕机，你的 AcquireLock 5 秒内会发生什么？",
            expected_defense="添加 context.WithTimeout 并实现降级策略",
            difficulty_delta=1,
        )
        assert c.attack_vector.target_file == "lock.go"

    def test_difficulty_delta_out_of_range(self):
        with pytest.raises(ValidationError):
            XRAGChallenge(action="INJECT", difficulty_delta=3)  # 超出 [-2, 2]
