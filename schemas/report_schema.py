"""
Task 2 — Geek Certification Report JSON Schema
极客认证报告：多维雷达图 + 防伪确权标识，Mock 数据动态生成，禁止硬编码
"""

from __future__ import annotations

import hashlib
import hmac
import random
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

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
    event_type: str  # e.g. "xrag_injection", "bug_fix", "timeout_defense"
    timestamp_sec: int
    description: str
    score_impact: float  # delta on combat_confidence


class AntiForgeryStamp(BaseModel):
    cert_id: str
    issued_at: str  # ISO 8601
    issuer: str = "HeartCert Oracle v2"
    algorithm: str = "HMAC-SHA256"
    signature: str  # hex digest


# ─── Root Report Model ────────────────────────────────────────────────────────

class GeekCertReport(BaseModel):
    cert_id: str
    candidate_id: str
    role: str
    issued_at: str
    expires_at: str
    combat_confidence: float = Field(..., ge=0.0, le=1.0)

    # 多维雷达图（6 维）
    radar_chart: list[RadarDimension] = Field(..., min_length=6, max_length=6)

    # 前 N 个验证原子能力
    top_abilities: list[AtomAbility]

    # 战役亮点切片
    combat_highlights: list[CombatHighlight]

    # B 端 rerank 弹药
    reranker_payload: str = Field(..., max_length=900)

    # 防伪确权标识
    anti_forgery: AntiForgeryStamp

    # 原始分向量摘要（32 维宏观层，用于前端可视化）
    vec_32_summary: list[float] = Field(..., min_length=32, max_length=32)


# ─── Mock Factory（动态生成，无硬编码）────────────────────────────────────────

_DIMENSION_NAMES = [
    "系统设计", "并发控制", "故障降级", "代码质量", "调试能力", "架构判断"
]

_ABILITY_NAMES = {
    # 示例映射（实际由 ability_library 动态加载）
    145: "Redis 分布式锁", 42: "Go 并发模型", 301: "PostgreSQL 索引优化",
    512: "熔断降级模式", 88: "内存泄漏诊断", 200: "微服务 RPC 设计",
    777: "CAS 乐观锁", 633: "连接池调优", 900: "gRPC 流式处理",
    1001: "容器资源限制", 55: "SQL 执行计划", 410: "缓存穿透防护",
}

_SIGNING_KEY = b"heartcert-internal-key-do-not-leak"


def _sign(cert_id: str, issued_at: str, candidate_id: str) -> str:
    payload = f"{cert_id}:{issued_at}:{candidate_id}".encode()
    return hmac.new(_SIGNING_KEY, payload, hashlib.sha256).hexdigest()


def mock_report(candidate_id: str | None = None, role: str = "AI 后端工程师") -> GeekCertReport:
    """
    动态生成极客认证报告 Mock 数据。
    所有随机数使用 secrets / random（带 seed 隔离），禁止魔法数字。
    """
    rng = random.Random(uuid.uuid4().int)  # 每次调用独立 seed，无硬编码固定值

    cid = candidate_id or str(uuid.uuid4())
    cert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    issued_at = now.isoformat()
    expires_at = now.replace(year=now.year + 2).isoformat()

    # 雷达图（6 维，分数随机但总体合理）
    radar: list[RadarDimension] = []
    for dim_name in _DIMENSION_NAMES:
        score = round(rng.uniform(40.0, 95.0), 1)
        percentile = round(rng.uniform(50.0, 99.0), 1)
        # 每维随机绑定 3–5 个原子 ID
        atom_sample = rng.sample(range(1, 1025), k=rng.randint(3, 5))
        radar.append(RadarDimension(
            dimension_name=dim_name,
            score=score,
            percentile=percentile,
            atom_ids_covered=atom_sample,
        ))

    # 前 5 个验证能力（从已知 ability 池中随机抽取）
    sampled_atoms = rng.sample(list(_ABILITY_NAMES.items()), k=min(5, len(_ABILITY_NAMES)))
    top_abilities = [
        AtomAbility(
            atom_id=atom_id,
            ability_name=name,
            score=round(rng.uniform(0.6, 1.0), 2),
            evidence_snippet=f"在沙盒战役 event#{rng.randint(1, 10)} 中实际验证，耗时 {rng.randint(3, 15)} 分钟完成修复",
        )
        for atom_id, name in sampled_atoms
    ]

    # 战役亮点
    event_types = ["xrag_injection", "bug_fix", "timeout_defense", "architecture_pivot"]
    highlights = [
        CombatHighlight(
            event_type=rng.choice(event_types),
            timestamp_sec=rng.randint(60, 3000),
            description=f"候选人在 {rng.choice(['Redis 宕机', '连接池耗尽', '死锁注入'])} 场景下完成实时重构",
            score_impact=round(rng.uniform(-0.1, 0.2), 2),
        )
        for _ in range(rng.randint(2, 4))
    ]

    combat_confidence = round(rng.uniform(0.55, 0.95), 2)

    reranker_payload = (
        f"候选人在归心私有 RPC 框架沙盒中，于 {rng.randint(8, 25)} 分钟内定位并修复了"
        f" {rng.choice(['goroutine 泄漏', 'Redis 分布式锁死锁', '连接池耗尽'])}问题，"
        f"展现了 {rng.choice(['强并发控制能力', '精准的故障降级思维', '扎实的系统设计判断力'])}。"
        f"X-RAG 注入 {rng.randint(1, 3)} 次异常，全部有效应对。"
        f"verified_skills: {', '.join(a.ability_name for a in top_abilities[:3])}。"
    )

    # 32 维宏观向量摘要（mock，0.0–1.0）
    vec_32 = [round(rng.uniform(0.0, 1.0), 4) for _ in range(32)]

    # 防伪标识
    sig = _sign(cert_id, issued_at, cid)
    stamp = AntiForgeryStamp(
        cert_id=cert_id,
        issued_at=issued_at,
        signature=sig,
    )

    return GeekCertReport(
        cert_id=cert_id,
        candidate_id=cid,
        role=role,
        issued_at=issued_at,
        expires_at=expires_at,
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
