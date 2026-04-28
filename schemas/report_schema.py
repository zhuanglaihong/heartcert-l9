"""
Task 2 — Geek Certification Report JSON Schema
极客认证报告：多维雷达图 + 防伪确权标识，Mock 数据动态生成，禁止硬编码
"""

from __future__ import annotations

import hashlib
import hmac
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field


# ─── Sub-models ───────────────────────────────────────────────────────────────

class RadarDimension(BaseModel):
    dimension_name: str
    score: float = Field(..., ge=0.0, le=100.0)
    percentile: float = Field(..., ge=0.0, le=100.0)
    atom_ids_covered: list[int]


class AtomAbility(BaseModel):
    atom_id: int = Field(..., ge=1, le=1024)
    ability_name: str
    score: float = Field(..., ge=0.0, le=1.0)
    evidence_snippet: str


class CombatHighlight(BaseModel):
    event_type: str  # "xrag_injection" | "bug_fix" | "timeout_defense" | "architecture_pivot"
    timestamp_sec: int
    description: str
    score_impact: float  # combat_confidence 的 delta 贡献（正负均可）


class AntiForgeryStamp(BaseModel):
    cert_id: str
    issued_at: str  # ISO 8601
    issuer: str = "HeartCert Oracle v2"
    algorithm: str = "HMAC-SHA256"
    # payload = cert_id:issued_at:candidate_id，HMAC-SHA256 hex digest
    signature: str


# ─── Root Report Model ────────────────────────────────────────────────────────

class GeekCertReport(BaseModel):
    cert_id: str
    candidate_id: str
    # session_id 链接回 CombatSession，支持战役追溯
    session_id: str
    role: str
    issued_at: str
    expires_at: str
    # 是否使用了 Fallback_Blueprint（PROVISIONING 超时降级）
    used_fallback: bool = False
    # 战役实际耗时（秒），用于验证 combat_confidence 公式
    battle_duration_sec: int | None = None
    combat_confidence: float = Field(..., ge=0.0, le=1.0)

    # 多维雷达图（6 维，对应 role_schema 的 6 大考核维度）
    radar_chart: list[RadarDimension] = Field(..., min_length=6, max_length=6)

    # 战役中验证的原子能力列表（仅 battle_log 有事件支撑的 atom_id）
    top_abilities: list[AtomAbility]

    # 战役亮点切片（前端时间轴渲染用）
    combat_highlights: list[CombatHighlight]

    # B 端 rerank 弹药（≤150 词，语义检索用）
    reranker_payload: str = Field(..., max_length=900)

    # 防伪确权标识
    anti_forgery: AntiForgeryStamp

    # 32 维宏观向量摘要（candidate_vectors.ability_vec_32，前端可视化用）
    vec_32_summary: list[float] = Field(..., min_length=32, max_length=32)


# ─── 签名工具 ─────────────────────────────────────────────────────────────────

# 生产环境从 HEARTCERT_SIGNING_KEY 环境变量读取；测试环境使用固定回退值
_SIGNING_KEY: bytes = os.environ.get(
    "HEARTCERT_SIGNING_KEY",
    "heartcert-dev-key-not-for-production",
).encode()


def _sign(cert_id: str, issued_at: str, candidate_id: str) -> str:
    payload = f"{cert_id}:{issued_at}:{candidate_id}".encode()
    return hmac.new(_SIGNING_KEY, payload, hashlib.sha256).hexdigest()


# ─── Mock Factory（动态生成，无硬编码固定值）────────────────────────────────

_DIMENSION_NAMES = [
    "系统设计", "并发控制", "故障降级", "代码质量", "调试能力", "架构判断"
]

_ABILITY_POOL: dict[int, str] = {
    145: "Redis 分布式锁",
    42:  "Go 并发模型",
    301: "PostgreSQL 索引优化",
    512: "熔断降级模式",
    88:  "内存泄漏诊断",
    200: "微服务 RPC 设计",
    777: "CAS 乐观锁",
    633: "连接池调优",
    900: "gRPC 流式处理",
    55:  "SQL 执行计划",
    410: "缓存穿透防护",
    720: "分布式追踪",
}

_FAULT_SCENARIOS = [
    "Redis 主节点宕机", "连接池耗尽（max_open_conns=0）", "goroutine 泄漏（channel 未关闭）",
    "分布式死锁（context 未传递）", "GIL 竞争导致数据不一致",
]

_BUG_FIX_METHODS = [
    "添加 context.WithTimeout 并实现 fallback 降级",
    "在 defer 中正确关闭 connection，消除资源泄漏",
    "引入 Redis Lua 脚本保证原子性",
    "用 sync.Once 替换裸 goroutine，修复 race condition",
]


def mock_report(
    candidate_id: str | None = None,
    session_id: str | None = None,
    role: str = "AI 后端工程师",
    used_fallback: bool = False,
    battle_duration_sec: int | None = None,
) -> GeekCertReport:
    """
    动态生成极客认证报告 Mock 数据。
    每次调用使用独立 RNG seed（uuid4().int），保证无两次相同输出，禁止魔法数字。
    """
    rng = random.Random(uuid.uuid4().int)

    cid = candidate_id or str(uuid.uuid4())
    sid = session_id or str(uuid.uuid4())
    cert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    issued_at = now.isoformat()
    # 使用 timedelta 避免 replace(year=...) 在闰年 2 月 29 日抛 ValueError
    expires_at = (now + timedelta(days=730)).isoformat()

    duration = battle_duration_sec if battle_duration_sec is not None else rng.randint(480, 1800)

    # 雷达图：6 维，每维随机绑定 3–5 个原子 ID
    radar: list[RadarDimension] = [
        RadarDimension(
            dimension_name=dim_name,
            score=round(rng.uniform(40.0, 95.0), 1),
            percentile=round(rng.uniform(50.0, 99.0), 1),
            atom_ids_covered=rng.sample(range(1, 1025), k=rng.randint(3, 5)),
        )
        for dim_name in _DIMENSION_NAMES
    ]

    # 战役验证能力（从 ability_pool 中随机抽取，score 仅含实战支撑的高分段）
    sampled = rng.sample(list(_ABILITY_POOL.items()), k=min(5, len(_ABILITY_POOL)))
    top_abilities = [
        AtomAbility(
            atom_id=aid,
            ability_name=name,
            score=round(rng.uniform(0.6, 1.0), 2),
            evidence_snippet=(
                f"event#{rng.randint(1, 10)} [t={rng.randint(120, duration)}s]: "
                f"{rng.choice(_BUG_FIX_METHODS)}"
            ),
        )
        for aid, name in sampled
    ]

    # 战役亮点（2–4 条，时间戳不重复）
    ts_pool = sorted(rng.sample(range(60, duration), k=min(4, duration - 60)))
    highlights = [
        CombatHighlight(
            event_type=rng.choice(["xrag_injection", "bug_fix", "timeout_defense", "architecture_pivot"]),
            timestamp_sec=ts,
            description=f"候选人在 {rng.choice(_FAULT_SCENARIOS)} 场景下，{rng.choice(_BUG_FIX_METHODS)}",
            score_impact=round(rng.uniform(-0.08, 0.18), 2),
        )
        for ts in ts_pool[:rng.randint(2, 4)]
    ]

    combat_confidence = round(rng.uniform(0.55, 0.95), 2)

    # reranker_payload：≤150 词，面向 B 端语义检索，无空洞评价词
    skill_names = ", ".join(a.ability_name for a in top_abilities[:3])
    fault = rng.choice(_FAULT_SCENARIOS)
    fix = rng.choice(_BUG_FIX_METHODS)
    reranker_payload = (
        f"候选人在归心私有 RPC 框架沙盒中，{duration // 60} 分钟内定位并修复了「{fault}」，"
        f"采用「{fix}」。X-RAG 共注入 {rng.randint(1, 3)} 次异常，全部完成即时重构。"
        f"已验证能力：{skill_names}。"
        f"暴露短板：{rng.choice(['边界条件处理不完整', '超时传递链断裂', '降级路径缺失幂等保护'])}。"
    )

    # 32 维宏观向量摘要（0.0–1.0）
    vec_32 = [round(rng.uniform(0.0, 1.0), 4) for _ in range(32)]

    # 防伪确权标识（HMAC-SHA256）
    sig = _sign(cert_id, issued_at, cid)
    stamp = AntiForgeryStamp(cert_id=cert_id, issued_at=issued_at, signature=sig)

    return GeekCertReport(
        cert_id=cert_id,
        candidate_id=cid,
        session_id=sid,
        role=role,
        issued_at=issued_at,
        expires_at=expires_at,
        used_fallback=used_fallback,
        battle_duration_sec=duration,
        combat_confidence=combat_confidence,
        radar_chart=radar,
        top_abilities=top_abilities,
        combat_highlights=highlights,
        reranker_payload=reranker_payload,
        anti_forgery=stamp,
        vec_32_summary=vec_32,
    )


if __name__ == "__main__":
    import json
    report = mock_report()
    print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
