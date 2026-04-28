"""
Task 2 — L9 Combat State Machine
FSM: PROVISIONING → COMBAT_ACTIVE → EVALUATING → CERTIFIED | FAILED
熔断：PROVISIONING 超时 >15s → 降级 Fallback_Blueprint
熔断：EVALUATING   超时 >60s → FAILED
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


# ─── 状态枚举 ─────────────────────────────────────────────────────────────────

class CombatState(str, Enum):
    PROVISIONING  = "PROVISIONING"   # Battlefield Agent 正在捏造私有框架
    COMBAT_ACTIVE = "COMBAT_ACTIVE"  # 候选人在沙盒中对抗
    EVALUATING    = "EVALUATING"     # Oracle Judge 打分中
    CERTIFIED     = "CERTIFIED"      # 评分完成，证书生成
    FAILED        = "FAILED"         # 超时 / 作弊 / 熔断降级失败


class CombatEvent(str, Enum):
    BLUEPRINT_READY    = "BLUEPRINT_READY"    # Battlefield Agent 输出成功
    BLUEPRINT_TIMEOUT  = "BLUEPRINT_TIMEOUT"  # PROVISIONING 超时 >15s，触发 Fallback
    BATTLE_COMPLETE    = "BATTLE_COMPLETE"    # 战役结束（候选人提交或时间到）
    JUDGE_COMPLETE     = "JUDGE_COMPLETE"     # Oracle Judge 打分完成
    JUDGE_TIMEOUT      = "JUDGE_TIMEOUT"      # EVALUATING 超时 >60s
    CHEAT_DETECTED     = "CHEAT_DETECTED"     # 作弊检测触发（切标签页、人脸消失等）


# ─── 会话数据 ─────────────────────────────────────────────────────────────────

@dataclass
class CombatSession:
    candidate_id: str
    role: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: CombatState = field(default=CombatState.PROVISIONING)
    blueprint_id: str | None = None
    used_fallback: bool = False
    battle_log: list[dict] = field(default_factory=list)
    judge_result: dict | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    combat_ended_at: datetime | None = None
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

    @property
    def battle_duration_sec(self) -> int | None:
        if self.combat_ended_at is None:
            return None
        return int((self.combat_ended_at - self.started_at).total_seconds())


# ─── 状态机 ───────────────────────────────────────────────────────────────────

# 合法状态转换表：(当前状态, 事件) → 目标状态
_TRANSITIONS: dict[tuple[CombatState, CombatEvent], CombatState] = {
    (CombatState.PROVISIONING,  CombatEvent.BLUEPRINT_READY):   CombatState.COMBAT_ACTIVE,
    (CombatState.PROVISIONING,  CombatEvent.BLUEPRINT_TIMEOUT): CombatState.COMBAT_ACTIVE,  # fallback 降级路径
    (CombatState.PROVISIONING,  CombatEvent.CHEAT_DETECTED):    CombatState.FAILED,
    (CombatState.COMBAT_ACTIVE, CombatEvent.BATTLE_COMPLETE):   CombatState.EVALUATING,
    (CombatState.COMBAT_ACTIVE, CombatEvent.CHEAT_DETECTED):    CombatState.FAILED,
    (CombatState.EVALUATING,    CombatEvent.JUDGE_COMPLETE):     CombatState.CERTIFIED,
    (CombatState.EVALUATING,    CombatEvent.JUDGE_TIMEOUT):      CombatState.FAILED,
}

# 终态：不接受任何事件
_TERMINAL_STATES = {CombatState.CERTIFIED, CombatState.FAILED}


class L9StateMachine:
    PROVISIONING_TIMEOUT_SEC = 15
    EVALUATING_TIMEOUT_SEC   = 60

    def __init__(self, session: CombatSession) -> None:
        self.session = session

    def transition(self, event: CombatEvent, payload: dict | None = None) -> CombatState:
        if self.session.state in _TERMINAL_STATES:
            raise InvalidTransitionError(
                f"Session {self.session.session_id} is in terminal state "
                f"{self.session.state}, cannot process event {event}"
            )
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
            self.session.combat_ended_at = datetime.now(timezone.utc)
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
    只处理 asyncio.TimeoutError，业务异常（JSON 解析失败等）直接上抛。
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
    L9 战役调度总线（伪代码）。
    真实部署时每个 Agent 调用均为 async，超时通过 CircuitBreaker 熔断降级。
    WebSocket 事件驱动层（on_trigger_event）由独立的 WS handler 挂载。
    """
    session = CombatSession(candidate_id=candidate_id, role=role)
    fsm = L9StateMachine(session)

    # ── 阶段 1：DNA 提取（Ingestion Agent）────────────────────────────────────
    dna = await ingestion_agent.run(
        candidate_id=candidate_id,
        role=role,
        resume_text=resume_text,
        ability_library=ability_library,
        role_schema_atom_ids=role_schema["atom_ids"],
    )

    # ── 阶段 2：战役蓝图生成（Battlefield Agent + 15s 熔断降级）──────────────

    async def _fallback_blueprint():
        fallback = await fallback_blueprint_fn(role=role, language=dna.dominant_language)
        fsm.transition(CombatEvent.BLUEPRINT_TIMEOUT, {"fallback_blueprint_id": fallback["blueprint_id"]})
        return fallback

    provisioning_breaker = CircuitBreaker(
        timeout_sec=L9StateMachine.PROVISIONING_TIMEOUT_SEC,
        fallback_fn=_fallback_blueprint,
    )
    blueprint = await provisioning_breaker.call(
        battlefield_agent.run(dna.model_dump(), role_schema)
    )
    if not session.used_fallback:
        fsm.transition(CombatEvent.BLUEPRINT_READY, {"blueprint_id": blueprint.blueprint_id})

    # ── 阶段 3：沙盒战役 + X-RAG 实时对抗（WebSocket 事件驱动）──────────────
    #
    # 真实部署：on_trigger_event 注册为 WebSocket message handler，
    # 由 IDE 插件推送 test_failure Error Log 或 5min checkpoint 事件。
    # 防抖逻辑在 WS 层实现（非 Diff 频率驱动）。
    #
    previous_challenges: list[dict] = []  # 防止重复攻击同一故障点

    async def on_trigger_event(event: dict, code_diff: str) -> None:
        challenge = await xrag_agent.run(
            trigger_event=event,
            code_diff=code_diff,
            blueprint_context={
                "framework_name": blueprint.framework_name,
                "bug_type": blueprint.bug_type,
                "target_atom_ids": blueprint.target_atom_ids,
            },
            difficulty_delta=_compute_difficulty_delta(session.battle_log),
            track="code" if dna.dominant_language else "prd",
            previous_challenges=previous_challenges,
        )
        if challenge.action == "INJECT":
            entry = {
                "type": "xrag_challenge",
                "challenge_id": challenge.challenge_id,
                "simulated_failure": challenge.attack_vector.simulated_failure if challenge.attack_vector else None,
                "modal_question": challenge.modal_question,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            session.battle_log.append(entry)
            # 记录已发动的攻击，避免重复注入同一故障
            previous_challenges.append({
                "challenge_id": challenge.challenge_id,
                "simulated_failure": entry["simulated_failure"],
            })

    # 伪代码：模拟战役期间的事件循环（真实实现替换为 WS handler 注册）
    # await websocket_combat_loop(session, on_trigger_event)

    # 战役结束，推进状态机
    fsm.transition(CombatEvent.BATTLE_COMPLETE, {"battle_log": session.battle_log})

    # ── 阶段 4：神谕评分（Oracle Judge + 60s 熔断 → FAILED）────────────────

    async def _judge_timeout_fallback():
        fsm.transition(CombatEvent.JUDGE_TIMEOUT, {"reason": "Oracle Judge evaluation timeout"})
        return None

    evaluating_breaker = CircuitBreaker(
        timeout_sec=L9StateMachine.EVALUATING_TIMEOUT_SEC,
        fallback_fn=_judge_timeout_fallback,
    )
    judge_result = await evaluating_breaker.call(
        oracle_judge_agent.run(
            role_schema=role_schema,
            battle_log=session.battle_log,
            expected_resolution_time_sec=role_schema.get("expected_time_sec", 900),
            actual_resolution_time_sec=session.battle_duration_sec or 0,
            candidate_dna=dna.model_dump(),  # 用于 1024D 平滑化决策
        )
    )
    if judge_result is not None:
        fsm.transition(CombatEvent.JUDGE_COMPLETE, {"judge_result": judge_result.model_dump()})

    return session


def _compute_difficulty_delta(battle_log: list[dict]) -> int:
    """根据已有战役日志估算难度调整量"""
    fix_count = sum(1 for e in battle_log if e.get("type") == "bug_fix")
    fail_count = sum(1 for e in battle_log if e.get("type") == "test_failure")
    if fix_count > fail_count:
        return 1
    if fail_count > fix_count * 2:
        return -1
    return 0
