"""
Module: workflow/state_machine.py
Tests: FSM 状态转换合法性、熔断边界、非法转换拦截
"""

import pytest
from workflow.state_machine import (
    CombatSession,
    CombatState,
    CombatEvent,
    L9StateMachine,
    InvalidTransitionError,
    CircuitBreaker,
)


class TestL9StateMachine:
    def _make_fsm(self) -> tuple[L9StateMachine, CombatSession]:
        session = CombatSession(candidate_id="c-001", role="Golang 后端")
        return L9StateMachine(session), session

    # ── 合法状态转换链 ────────────────────────────────────────────────────────

    def test_full_happy_path(self):
        fsm, session = self._make_fsm()
        assert session.state == CombatState.PROVISIONING

        fsm.transition(CombatEvent.BLUEPRINT_READY, {"blueprint_id": "bp-001"})
        assert session.state == CombatState.COMBAT_ACTIVE
        assert session.blueprint_id == "bp-001"

        fsm.transition(CombatEvent.BATTLE_COMPLETE, {"battle_log": [{"type": "bug_fix"}]})
        assert session.state == CombatState.EVALUATING
        assert len(session.battle_log) == 1

        fsm.transition(CombatEvent.JUDGE_COMPLETE, {"judge_result": {"combat_confidence": 0.9}})
        assert session.state == CombatState.CERTIFIED

    def test_fallback_path_on_provisioning_timeout(self):
        fsm, session = self._make_fsm()
        fsm.transition(CombatEvent.BLUEPRINT_TIMEOUT, {"fallback_blueprint_id": "fb-001"})
        assert session.state == CombatState.COMBAT_ACTIVE
        assert session.used_fallback is True
        assert session.blueprint_id == "fb-001"

    def test_evaluating_timeout_leads_to_failed(self):
        fsm, session = self._make_fsm()
        fsm.transition(CombatEvent.BLUEPRINT_READY, {"blueprint_id": "bp-001"})
        fsm.transition(CombatEvent.BATTLE_COMPLETE, {"battle_log": []})
        fsm.transition(CombatEvent.JUDGE_TIMEOUT, {"reason": "timeout"})
        assert session.state == CombatState.FAILED
        assert session.error == "timeout"

    def test_cheat_detected_leads_to_failed_from_provisioning(self):
        fsm, session = self._make_fsm()
        fsm.transition(CombatEvent.CHEAT_DETECTED, {"reason": "tab_switch"})
        assert session.state == CombatState.FAILED

    def test_cheat_detected_leads_to_failed_from_combat_active(self):
        fsm, session = self._make_fsm()
        fsm.transition(CombatEvent.BLUEPRINT_READY, {"blueprint_id": "bp-001"})
        fsm.transition(CombatEvent.CHEAT_DETECTED, {"reason": "face_not_detected"})
        assert session.state == CombatState.FAILED

    # ── 非法转换拦截 ──────────────────────────────────────────────────────────

    def test_illegal_transition_raises(self):
        fsm, _ = self._make_fsm()
        with pytest.raises(InvalidTransitionError):
            # PROVISIONING 不能直接接收 BATTLE_COMPLETE
            fsm.transition(CombatEvent.BATTLE_COMPLETE)

    def test_no_transition_from_certified(self):
        fsm, session = self._make_fsm()
        fsm.transition(CombatEvent.BLUEPRINT_READY, {"blueprint_id": "bp-001"})
        fsm.transition(CombatEvent.BATTLE_COMPLETE, {"battle_log": []})
        fsm.transition(CombatEvent.JUDGE_COMPLETE, {"judge_result": {}})
        assert session.state == CombatState.CERTIFIED
        with pytest.raises(InvalidTransitionError):
            fsm.transition(CombatEvent.BLUEPRINT_READY)

    # ── 状态历史记录 ──────────────────────────────────────────────────────────

    def test_state_history_recorded(self):
        fsm, session = self._make_fsm()
        fsm.transition(CombatEvent.BLUEPRINT_READY, {"blueprint_id": "bp-001"})
        fsm.transition(CombatEvent.BATTLE_COMPLETE, {"battle_log": []})
        assert len(session.state_history) == 2
        assert session.state_history[0]["from"] == "PROVISIONING"
        assert session.state_history[0]["to"] == "COMBAT_ACTIVE"


# ─── CircuitBreaker ───────────────────────────────────────────────────────────

import asyncio


class TestCircuitBreaker:
    async def _fast_coro(self):
        return "fast_result"

    async def _slow_coro(self):
        await asyncio.sleep(10)
        return "slow_result"

    async def _fallback(self):
        return "fallback_result"

    def test_fast_coro_returns_result(self):
        breaker = CircuitBreaker(timeout_sec=2, fallback_fn=self._fallback)
        result = asyncio.run(breaker.call(self._fast_coro()))
        assert result == "fast_result"

    def test_slow_coro_triggers_fallback(self):
        breaker = CircuitBreaker(timeout_sec=1, fallback_fn=self._fallback)
        result = asyncio.run(breaker.call(self._slow_coro()))
        assert result == "fallback_result"
