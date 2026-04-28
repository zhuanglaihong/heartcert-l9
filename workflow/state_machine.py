"""
Task 2 — L9 Combat State Machine
FSM: PROVISIONING → COMBAT_ACTIVE → EVALUATING → CERTIFIED | FAILED
含熔断机制：PROVISIONING 超时 >15s 降级 Fallback，EVALUATING 超时 >60s → FAILED
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ─── 状态枚举 ─────────────────────────────────────────────────────────────────

class CombatState(str, Enum):
    PROVISIONING  = "PROVISIONING"   # Battlefield Agent 正在捏造私有框架
    COMBAT_ACTIVE = "COMBAT_ACTIVE"  # 候选人在沙盒中对抗
    EVALUATING    = "EVALUATING"     # Oracle Judge 打分中
    CERTIFIED     = "CERTIFIED"      # 评分完成，证书生成
    FAILED        = "FAILED"         # 超时 / 作弊 / 熔断降级失败


class CombatEvent(str, Enum):
    BLUEPRINT_READY    = "BLUEPRINT_READY"    # Battlefield Agent 输出成功
    BLUEPRINT_TIMEOUT  = "BLUEPRINT_TIMEOUT"  # PROVISIONING 超时 >15s
    COMBAT_START       = "COMBAT_START"       # 候选人开始作答
    BATTLE_COMPLETE    = "BATTLE_COMPLETE"    # 战役结束（候选人提交或时间到）
    JUDGE_COMPLETE     = "JUDGE_COMPLETE"     # Oracle Judge 打分完成
    JUDGE_TIMEOUT      = "JUDGE_TIMEOUT"      # EVALUATING 超时 >60s
    CHEAT_DETECTED     = "CHEAT_DETECTED"     # 作弊检测触发


# ─── 会话数据 ─────────────────────────────────────────────────────────────────

@dataclass
class CombatSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    candidate_id: str = ""
    role: str = ""
    state: CombatState = CombatState.PROVISIONING
    blueprint_id: str | None = None
    used_fallback: bool = False
    battle_log: list[dict] = field(default_factory=list)
    judge_result: dict | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state_history: list[dict] = field(default_factory=list)
    error: str | None = None

    def record_transition(self, new_state: CombatState, event: CombatEvent) -> None:
        self.state_history.append({
            "from": self.state.value,
            "to": new_state.value,
            "event": event.value,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        self.state = new_state


# ─── 状态机 ───────────────────────────────────────────────────────────────────

# 合法状态转换表
_TRANSITIONS: dict[tuple[CombatState, CombatEvent], CombatState] = {
    (CombatState.PROVISIONING,  CombatEvent.BLUEPRINT_READY):   CombatState.COMBAT_ACTIVE,
    (CombatState.PROVISIONING,  CombatEvent.BLUEPRINT_TIMEOUT): CombatState.COMBAT_ACTIVE,  # fallback path
    (CombatState.PROVISIONING,  CombatEvent.CHEAT_DETECTED):    CombatState.FAILED,
    (CombatState.COMBAT_ACTIVE, CombatEvent.BATTLE_COMPLETE):   CombatState.EVALUATING,
    (CombatState.COMBAT_ACTIVE, CombatEvent.CHEAT_DETECTED):    CombatState.FAILED,
    (CombatState.EVALUATING,    CombatEvent.JUDGE_COMPLETE):     CombatState.CERTIFIED,
    (CombatState.EVALUATING,    CombatEvent.JUDGE_TIMEOUT):      CombatState.FAILED,
}


class L9StateMachine:
    PROVISIONING_TIMEOUT_SEC = 15
    EVALUATING_TIMEOUT_SEC   = 60

    def __init__(self, session: CombatSession) -> None:
        self.session = session

    def transition(self, event: CombatEvent, payload: dict | None = None) -> CombatState:
        key = (self.session.state, event)
        next_state = _TRANSITIONS.get(key)
        if next_state is None:
            raise InvalidTransitionError(
                f"No transition from {self.session.state} on event {event}"
            )
        self.session.record_transition(next_state, event)
        if payload:
            self._apply_payload(event, payload)
        return next_state

    def _apply_payload(self, event: CombatEvent, payload: dict) -> None:
        if event == CombatEvent.BLUEPRINT_READY:
            self.session.blueprint_id = payload.get("blueprint_id")
        elif event == CombatEvent.BLUEPRINT_TIMEOUT:
            self.session.blueprint_id = payload.get("fallback_blueprint_id")
            self.session.used_fallback = True
        elif event == CombatEvent.BATTLE_COMPLETE:
            self.session.battle_log = payload.get("battle_log", [])
        elif event == CombatEvent.JUDGE_COMPLETE:
            self.session.judge_result = payload.get("judge_result")
        elif event in (CombatEvent.JUDGE_TIMEOUT, CombatEvent.CHEAT_DETECTED):
            self.session.error = payload.get("reason", event.value)


class InvalidTransitionError(Exception):
    pass


# ─── 熔断器 ───────────────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    包裹异步 Agent 调用，超时后触发熔断降级。
    不捕获业务异常（JSON 解析失败等），只处理超时。
    """

    def __init__(self, timeout_sec: int, fallback_fn) -> None:
        self._timeout = timeout_sec
        self._fallback = fallback_fn

    async def call(self, coro, *fallback_args, **fallback_kwargs):
        try:
            return await asyncio.wait_for(coro, timeout=self._timeout)
        except asyncio.TimeoutError:
            return await self._fallback(*fallback_args, **fallback_kwargs)


# ─── Agent 调度总线（Python 伪代码，展示完整编排逻辑）────────────────────────

async def run_l9_combat(
    candidate_id: str,
    role: str,
    resume_text: str,
    ability_library: dict,
    role_schema: dict,
    ingestion_agent,
    battlefield_agent,
    xrag_agent,
    oracle_judge_agent,
    fallback_blueprint_fn,
) -> CombatSession:
    """
    完整的 L9 战役调度总线。
    真实部署时，每个 Agent 调用均为 async，通过 asyncio.wait_for 实现超时熔断。
    """
    session = CombatSession(candidate_id=candidate_id, role=role)
    fsm = L9StateMachine(session)

    # ── 阶段 1：DNA 提取 ───────────────────────────────────────────────────────
    dna = await ingestion_agent.run(
        candidate_id=candidate_id,
        role=role,
        resume_text=resume_text,
        ability_library=ability_library,
        role_schema_atom_ids=role_schema["atom_ids"],
    )

    # ── 阶段 2：战役蓝图生成（带 15s 熔断降级）───────────────────────────────
    breaker = CircuitBreaker(
        timeout_sec=L9StateMachine.PROVISIONING_TIMEOUT_SEC,
        fallback_fn=fallback_blueprint_fn,
    )

    battlefield_coro = battlefield_agent.run(
        candidate_dna=dna.model_dump(),
        role_blueprint_config=role_schema,
    )

    try:
        blueprint = await asyncio.wait_for(
            battlefield_agent.run(dna.model_dump(), role_schema),
            timeout=L9StateMachine.PROVISIONING_TIMEOUT_SEC,
        )
        fsm.transition(CombatEvent.BLUEPRINT_READY, {"blueprint_id": blueprint.blueprint_id})
    except asyncio.TimeoutError:
        fallback = await fallback_blueprint_fn(role=role, language=dna.dominant_language)
        fsm.transition(CombatEvent.BLUEPRINT_TIMEOUT, {"fallback_blueprint_id": fallback["blueprint_id"]})

    # ── 阶段 3：沙盒战役（X-RAG 实时对抗，由外部 WebSocket 事件驱动）──────────
    # 此处为伪代码框架，真实实现中 battle_log 由 WebSocket handler 实时追加
    battle_log: list[dict] = []

    async def on_trigger_event(event: dict, code_diff: str) -> None:
        """WebSocket 回调：防抖后触发 X-RAG"""
        challenge = await xrag_agent.run(
            trigger_event=event,
            code_diff=code_diff,
            blueprint_context={"framework_name": blueprint.framework_name, "bug_type": blueprint.bug_type},
            difficulty_delta=_compute_difficulty_delta(battle_log),
        )
        if challenge.action == "INJECT":
            battle_log.append({
                "type": "xrag_challenge",
                "challenge_id": challenge.challenge_id,
                "modal_question": challenge.modal_question,
            })

    # 战役结束后推进状态
    fsm.transition(CombatEvent.BATTLE_COMPLETE, {"battle_log": battle_log})

    # ── 阶段 4：神谕评分（带 60s 熔断）───────────────────────────────────────
    try:
        judge_result = await asyncio.wait_for(
            oracle_judge_agent.run(
                role_schema=role_schema,
                battle_log=battle_log,
                expected_resolution_time_sec=role_schema.get("expected_time_sec", 900),
                actual_resolution_time_sec=_compute_actual_time(session),
            ),
            timeout=L9StateMachine.EVALUATING_TIMEOUT_SEC,
        )
        fsm.transition(CombatEvent.JUDGE_COMPLETE, {"judge_result": judge_result.model_dump()})
    except asyncio.TimeoutError:
        fsm.transition(CombatEvent.JUDGE_TIMEOUT, {"reason": "Oracle Judge evaluation timeout"})

    return session


def _compute_difficulty_delta(battle_log: list[dict]) -> int:
    """根据已有战役日志估算难度调整量（简化版）"""
    fix_count = sum(1 for e in battle_log if e.get("type") == "bug_fix")
    fail_count = sum(1 for e in battle_log if e.get("type") == "test_failure")
    if fix_count > fail_count:
        return 1
    elif fail_count > fix_count * 2:
        return -1
    return 0


def _compute_actual_time(session: CombatSession) -> int:
    elapsed = datetime.now(timezone.utc) - session.started_at
    return int(elapsed.total_seconds())
