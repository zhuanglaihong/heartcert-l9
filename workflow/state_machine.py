"""
Task 2 — L9 Combat State Machine + Harness Engineering
FSM: PROVISIONING → COMBAT_ACTIVE → EVALUATING → CERTIFIED | FAILED
熔断：PROVISIONING 超时 >15s → 降级 Fallback_Blueprint
熔断：EVALUATING   超时 >60s → FAILED
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import ValidationError

logger = logging.getLogger(__name__)


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


# ─── LLM 调用 Harness ─────────────────────────────────────────────────────────

class LLMCallError(Exception):
    """LLM 输出在 MAX_RETRIES 次重试后仍无法通过 Pydantic 验证时抛出。"""


class LLMHarness:
    """
    LLM 调用 Harness —— 所有 Agent.run() 必须经过此处，提供三重保障：

    1. 输出验证重试（最多 MAX_RETRIES 次）
       JSON 解析失败或 Pydantic 验证失败时，自动重试。
       生产环境第 2+ 次调用会将校验错误拼入 user_msg，引导 LLM 对照 Schema 自我修正。

    2. Prompt Injection 检测
       LLM 输出含 `_security.injection_attempt_blocked: true` 时写入告警日志；
       不阻断业务流程（LLM 已在 prompt 层拦截注入，此处只做审计记录）。

    3. 结构化审计日志
       每次调用记录 session_id / label / attempt / latency_ms / 成功|失败原因，
       构成完整的 LLM 调用账本，供事后审计和费用追踪。
    """

    MAX_RETRIES: int = 3
    # 置信度低于此阈值时 Oracle Judge 结果不予确权
    MIN_CONFIDENCE: float = 0.1

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._audit_log: list[dict] = []

    async def call(self, agent_fn: Any, label: str, **kwargs: Any) -> Any:
        """
        调用 agent_fn(**kwargs)，失败时最多重试 MAX_RETRIES 次。

        重试触发条件：json.JSONDecodeError 或 pydantic.ValidationError
        非重试异常（asyncio.TimeoutError 等）直接上抛，由 CircuitBreaker 处理。
        """
        last_error: str | None = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            t0 = time.perf_counter()
            try:
                # 第 2+ 次重试：将上次的校验错误反馈给 Agent，
                # Agent 内部将其附加到 user_msg，让 LLM 看到自己的错误并修正。
                call_kwargs = dict(kwargs)
                if last_error and attempt > 1:
                    call_kwargs["_retry_feedback"] = (
                        f"[SYSTEM: RETRY {attempt}/{self.MAX_RETRIES}] "
                        f"上次输出未能通过 Schema 校验，错误原因：{last_error[:300]}。"
                        f"请仔细对照 JSON Schema 重新输出，不得遗漏必填字段，"
                        f"所有数值必须在约束范围内。"
                    )

                result = await agent_fn(**call_kwargs)
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)

                # ── Prompt Injection 检测 ──────────────────────────────────
                raw: dict = result.model_dump() if hasattr(result, "model_dump") else {}
                sec: dict = raw.get("_security", {})
                if sec.get("injection_attempt_blocked"):
                    logger.warning(
                        "[harness] INJECTION_BLOCKED session=%s label=%s pattern=%r",
                        self._session_id, label, sec.get("pattern"),
                    )
                    self._audit_log.append({
                        "label": label, "attempt": attempt,
                        "status": "injection_blocked",
                        "pattern": sec.get("pattern"),
                        "latency_ms": latency_ms,
                    })

                self._audit_log.append({
                    "label": label, "attempt": attempt,
                    "status": "ok", "latency_ms": latency_ms,
                })
                logger.info(
                    "[harness] OK session=%s label=%s attempt=%d latency=%.1fms",
                    self._session_id, label, attempt, latency_ms,
                )
                return result

            except (json.JSONDecodeError, ValidationError) as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                last_error = str(exc)
                self._audit_log.append({
                    "label": label, "attempt": attempt,
                    "status": "validation_error",
                    "error": last_error[:200],
                    "latency_ms": latency_ms,
                })
                logger.warning(
                    "[harness] RETRY session=%s label=%s attempt=%d/%d err=%s",
                    self._session_id, label, attempt, self.MAX_RETRIES, last_error[:200],
                )
                if attempt == self.MAX_RETRIES:
                    raise LLMCallError(
                        f"[{label}] failed after {self.MAX_RETRIES} attempts. "
                        f"Last error: {last_error}"
                    ) from exc

    @property
    def audit_log(self) -> list[dict]:
        return list(self._audit_log)


# ─── X-RAG 战役主循环（WebSocket 事件驱动）──────────────────────────────────

# 真实部署：IDE 插件通过 WebSocket 推送 test_failure / checkpoint 事件；
# 下方 SIMULATED_EVENTS 模拟该流，展示完整的事件驱动编排逻辑。
_SIMULATED_COMBAT_EVENTS: list[dict] = [
    {
        "type": "test_failure",
        "error_log": (
            "FAIL TestAcquireLock: goroutine leak detected, 47 goroutines leaked\n"
            "panic: runtime error: send on closed channel"
        ),
        "code_diff": (
            "func AcquireLock(key string) (func(), error) {\n"
            "  ch := make(chan struct{})\n"
            "  go func() { lockCh <- key }()  // BUG: goroutine never exits if lockCh full\n"
            "  return func() { close(ch) }, nil\n"
            "}"
        ),
    },
    {
        "type": "checkpoint",
        "error_log": "",
        "code_diff": (
            "// candidate has been on connection pool management for >5min\n"
            "func NewPool(dsn string) *sql.DB {\n"
            "  db, _ := sql.Open(\"postgres\", dsn)  // BUG: max_open_conns never set\n"
            "  return db\n"
            "}"
        ),
    },
]


async def _run_combat_with_xrag(
    session: CombatSession,
    xrag_agent: Any,
    blueprint: Any,
    dna: Any,
    harness: LLMHarness,
) -> None:
    """
    X-RAG 实时对抗阶段。

    生产实现：
        ws_handler = on_trigger_event  # 注册为 WebSocket message handler
        await websockets.serve(ws_handler, host, port)

    伪代码实现（此处）：
        遍历 _SIMULATED_COMBAT_EVENTS，模拟 IDE 插件的事件推送，
        展示完整的 Harness 调用链 + 防重复攻击机制。
    """
    previous_challenges: list[dict] = []  # 跨整个战役存活，防止同一故障点被重复注入

    for raw_event in _SIMULATED_COMBAT_EVENTS:
        trigger_event = {"type": raw_event["type"], "error_log": raw_event["error_log"]}
        code_diff = raw_event["code_diff"]

        # X-RAG 调用经过 Harness：JSON 校验失败最多重试 3 次
        challenge = await harness.call(
            xrag_agent.run,
            label="xrag",
            trigger_event=trigger_event,
            code_diff=code_diff,
            blueprint_context={
                "framework_name":  blueprint.framework_name,
                "bug_type":        blueprint.bug_type,
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
                "simulated_failure": (
                    challenge.attack_vector.simulated_failure
                    if challenge.attack_vector else None
                ),
                "modal_question": challenge.modal_question,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            session.battle_log.append(entry)
            # 记录已发动的攻击：challenge_id + simulated_failure 双重去重
            previous_challenges.append({
                "challenge_id": challenge.challenge_id,
                "simulated_failure": entry["simulated_failure"],
            })
            logger.info(
                "[combat] INJECT session=%s challenge=%s failure=%r modal_len=%d",
                session.session_id,
                challenge.challenge_id,
                entry["simulated_failure"],
                len(challenge.modal_question or ""),
            )
        else:
            logger.debug(
                "[combat] NO_TRIGGER session=%s reason=%s",
                session.session_id, challenge.reason,
            )


# ─── Agent 调度总线（Python 伪代码，展示完整编排逻辑）────────────────────────

async def run_l9_combat(
    candidate_id: str,
    role: str,
    resume_text: str,
    ability_library: dict,
    role_schema: dict,
    ingestion_agent: Any,
    battlefield_agent: Any,
    xrag_agent: Any,
    oracle_judge_agent: Any,
    fallback_blueprint_fn: Any,
) -> CombatSession:
    """
    L9 战役调度总线。

    Harness Engineering 核心模式：
    - 所有 LLM 调用经由 LLMHarness.call()，自动处理 JSON/Pydantic 校验重试
    - 两处超时熔断由 CircuitBreaker 处理（PROVISIONING 15s / EVALUATING 60s）
    - X-RAG 阶段由 _run_combat_with_xrag 以事件驱动方式展开
    - Oracle Judge 输出加置信度门控，极低置信度触发 CHEAT_DETECTED → FAILED
    """
    session = CombatSession(candidate_id=candidate_id, role=role)
    fsm     = L9StateMachine(session)
    harness = LLMHarness(session.session_id)  # 统一 Harness，跨阶段共享审计日志

    logger.info("[combat] START session=%s candidate=%s role=%s",
                session.session_id, candidate_id, role)

    # ── 阶段 1: Ingestion Agent ───────────────────────────────────────────────
    # 无超时熔断（Ingestion 失败 = 简历不可解析，战役不应开始）；
    # Harness 保证 CandidateDNA Pydantic 验证通过，否则最多重试 3 次后抛 LLMCallError。
    dna = await harness.call(
        ingestion_agent.run,
        label="ingestion",
        candidate_id=candidate_id,
        role=role,
        resume_text=resume_text,
        ability_library=ability_library,
        role_schema_atom_ids=role_schema["atom_ids"],
    )
    logger.info("[combat] DNA_READY session=%s abilities=%d missing=%d",
                session.session_id, len(dna.raw_abilities), len(dna.missing_areas))

    # ── 阶段 2: Battlefield Agent（CircuitBreaker 15s + Harness 验证）─────────
    async def _fallback_blueprint() -> Any:
        fallback = await fallback_blueprint_fn(role=role, language=dna.dominant_language)
        fsm.transition(CombatEvent.BLUEPRINT_TIMEOUT,
                       {"fallback_blueprint_id": fallback["blueprint_id"]})
        logger.info("[combat] FALLBACK_BLUEPRINT session=%s", session.session_id)
        return fallback

    provisioning_breaker = CircuitBreaker(
        timeout_sec=L9StateMachine.PROVISIONING_TIMEOUT_SEC,
        fallback_fn=_fallback_blueprint,
    )
    # CircuitBreaker 包裹 Harness 协程：超时由 CB 处理，JSON/Pydantic 错误由 Harness 重试
    blueprint = await provisioning_breaker.call(
        harness.call(
            battlefield_agent.run,
            label="battlefield",
            candidate_dna=dna.model_dump(),
            role_blueprint_config=role_schema,
        )
    )
    if not session.used_fallback:
        fsm.transition(CombatEvent.BLUEPRINT_READY,
                       {"blueprint_id": blueprint.blueprint_id})
        logger.info("[combat] BLUEPRINT_READY session=%s framework=%s difficulty=%d",
                    session.session_id,
                    blueprint.framework_name,
                    blueprint.difficulty_rating)

    # ── 阶段 3: 沙盒战役 + X-RAG 实时对抗 ───────────────────────────────────
    # WebSocket 事件驱动；此处以 _run_combat_with_xrag 展示完整的事件处理逻辑
    await _run_combat_with_xrag(session, xrag_agent, blueprint, dna, harness)
    fsm.transition(CombatEvent.BATTLE_COMPLETE, {"battle_log": session.battle_log})
    logger.info("[combat] BATTLE_COMPLETE session=%s log_entries=%d duration_sec=%s",
                session.session_id,
                len(session.battle_log),
                session.battle_duration_sec)

    # ── 阶段 4: Oracle Judge（CircuitBreaker 60s + 置信度门控）────────────────
    async def _judge_timeout_fallback() -> None:
        fsm.transition(CombatEvent.JUDGE_TIMEOUT,
                       {"reason": "Oracle Judge evaluation timeout"})
        logger.warning("[combat] JUDGE_TIMEOUT session=%s", session.session_id)
        return None

    evaluating_breaker = CircuitBreaker(
        timeout_sec=L9StateMachine.EVALUATING_TIMEOUT_SEC,
        fallback_fn=_judge_timeout_fallback,
    )
    judge_result = await evaluating_breaker.call(
        harness.call(
            oracle_judge_agent.run,
            label="oracle_judge",
            role_schema=role_schema,
            battle_log=session.battle_log,
            expected_resolution_time_sec=role_schema.get("expected_time_sec", 900),
            actual_resolution_time_sec=session.battle_duration_sec or 0,
            candidate_dna=dna.model_dump(),  # 供 1024D 平滑化决策
        )
    )

    if judge_result is None:
        # JUDGE_TIMEOUT 路径：fallback 已推进 FSM → FAILED
        return session

    # 置信度门控：极低置信度表明战役数据严重不足或评分不可信，拒绝确权
    if judge_result.combat_confidence < LLMHarness.MIN_CONFIDENCE:
        fsm.transition(CombatEvent.CHEAT_DETECTED, {
            "reason": (
                f"combat_confidence={judge_result.combat_confidence:.2f} "
                f"below minimum threshold {LLMHarness.MIN_CONFIDENCE}"
            )
        })
        logger.warning("[combat] CONFIDENCE_GATE_FAIL session=%s confidence=%.2f",
                       session.session_id, judge_result.combat_confidence)
        return session

    fsm.transition(CombatEvent.JUDGE_COMPLETE,
                   {"judge_result": judge_result.model_dump()})
    logger.info(
        "[combat] CERTIFIED session=%s confidence=%.2f "
        "skills=%s harness_calls=%d",
        session.session_id,
        judge_result.combat_confidence,
        judge_result.verified_skills,
        len(harness.audit_log),
    )
    return session


def _compute_difficulty_delta(battle_log: list[dict]) -> int:
    """根据已有战役日志估算难度调整量：修复多则升级，失败多则降级给线索。"""
    fix_count  = sum(1 for e in battle_log if e.get("type") == "bug_fix")
    fail_count = sum(1 for e in battle_log if e.get("type") == "test_failure")
    if fix_count > fail_count:
        return 1
    if fail_count > fix_count * 2:
        return -1
    return 0
