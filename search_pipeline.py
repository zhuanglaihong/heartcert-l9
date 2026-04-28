"""
Task 4 — Hybrid Search Pipeline (FastAPI)
B 端混合检索路由管线：Filter Gate → L1(32D) → L2(128D) → L3(1024D+Sparse) → RRF → Rerank → Top3
全部 DB/RPC 调用使用 Mock 函数替代，无需连接真实数据库。
手写 RRF 算法（k=60），延迟目标 ≤ 1.5s。
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

app = FastAPI(title="HeartCert L9 Hybrid Search Pipeline", version="1.0.0")


# ─── 请求 / 响应模型 ──────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query_text: str = Field(..., min_length=2, description="HR 自然语言搜索词")
    requirement_profile_id: str | None = Field(None, description="已固化的需求 profile ID，优先使用")
    filters: dict[str, Any] = Field(default_factory=dict, description="硬过滤条件：城市/薪资/经验等")
    top_k: int = Field(default=3, ge=1, le=10)


class CandidateScore(BaseModel):
    candidate_id: str
    score_32: float
    score_128: float
    score_1024: float
    score_sparse: float
    rrf_score: float
    rerank_score: float
    # 0.4·RRF（多路召回层信号汇聚）+ 0.6·rerank（Cross-Encoder 深度语义精排）
    # 60% 给 reranker：cross-attention 全文对比精度远高于向量近似
    final_score: float
    matched_abilities: list[str]
    reranker_payload: str


class SearchResponse(BaseModel):
    session_id: str
    query_text: str
    total_latency_ms: float
    stage_latencies_ms: dict[str, float]
    results: list[CandidateScore]


# ─── Mock 候选人池（模块级固定，保证测试稳定性）─────────────────────────────

_MOCK_CANDIDATES: list[str] = [str(uuid.uuid4()) for _ in range(500)]


# ─── Mock DB / RPC 函数 ───────────────────────────────────────────────────────
# 每个函数使用由其输入参数派生的确定性 RNG，不共享任何模块级可变状态，
# 从而消除并发请求之间的 RNG 交叉污染。

def _mock_parse_query(query_text: str) -> dict:
    """模拟 Query Parser Agent：输出 target_vectors + extracted_tags"""
    rng = random.Random(hash(query_text))
    return {
        "target_vec_32":   [round(rng.uniform(0.0, 1.0), 4) for _ in range(32)],
        "target_vec_128":  [round(rng.uniform(0.0, 1.0), 4) for _ in range(128)],
        "target_vec_1024": [round(rng.uniform(0.0, 1.0), 4) for _ in range(1024)],
        "extracted_tags":  query_text.split()[:5],
    }


def _mock_filter_gate(candidate_ids: list[str], filters: dict) -> list[str]:
    """
    模拟硬过滤：城市、薪资、经验、可见性、私有池。
    Mock 逻辑：随机保留 80% 候选人（模拟过滤率）。
    """
    rng = random.Random(str(filters))
    return [c for c in candidate_ids if rng.random() < 0.80]


def _mock_recall_l1(
    target_vec_32: list[float],
    candidate_pool: list[str],
    limit: int = 200,
) -> list[tuple[str, int]]:
    """
    L1 粗召回：32D HNSW cosine 相似度，在 Filter Gate 输出池上运行。
    返回 (candidate_id, rank) 列表，禁止返回完整行数据。
    """
    rng = random.Random(hash(tuple(target_vec_32[:4])))
    candidates = candidate_pool[:]
    rng.shuffle(candidates)
    return [(c, rank + 1) for rank, c in enumerate(candidates[:limit])]


def _mock_recall_l2(
    target_vec_128: list[float],
    candidate_ids: list[str],
    limit: int = 80,
) -> list[tuple[str, int]]:
    """L2 中召回：128D HNSW，仅在 L1 结果集上运行"""
    rng = random.Random(hash(tuple(target_vec_128[:4])))
    subset = [c for c in candidate_ids if rng.random() < 0.85][:limit]
    rng.shuffle(subset)
    return [(c, rank + 1) for rank, c in enumerate(subset)]


def _mock_recall_l3(
    target_vec_1024: list[float],
    candidate_ids: list[str],
    limit: int = 40,
) -> list[tuple[str, int]]:
    """L3 精召回：1024D HNSW + must_have_abilities hard boost"""
    rng = random.Random(hash(tuple(target_vec_1024[:4])))
    subset = [c for c in candidate_ids if rng.random() < 0.80][:limit]
    rng.shuffle(subset)
    return [(c, rank + 1) for rank, c in enumerate(subset)]


def _mock_sparse_recall(
    tags: list[str],
    candidate_pool: list[str],
    limit: int = 40,
) -> list[tuple[str, int]]:
    """
    稀疏召回：GIN 索引 BM25 匹配 profile_data.verified_skills。
    与 L1 并发运行（独立 DB 查询路径）；补漏过滤在应用层完成。
    """
    rng = random.Random(hash(tuple(sorted(tags))))
    candidates = candidate_pool[:]
    rng.shuffle(candidates)
    return [(c, rank + 1) for rank, c in enumerate(candidates[:limit])]


def _mock_fetch_reranker_payloads(
    candidate_ids: list[str],
    seed: int = 0,
) -> dict[str, str]:
    """
    批量拉取 Top-N reranker_payload（只在 RRF 出最终 Top-30 后才调用）。
    解决老架构 OOM 风险：RRF 阶段只传 (candidate_id, rank)，此处才拉全量文本。
    """
    rng = random.Random(seed)
    return {
        cid: (
            f"候选人 {cid[:8]} 在分布式锁沙盒中展现了强并发控制能力，"
            f"处理了 Redis 宕机和 goroutine 泄漏，耗时约 {rng.randint(8, 25)} 分钟，"
            f"verified_skills: Golang, Redis, 分布式锁。"
        )
        for cid in candidate_ids
    }


def _mock_cross_encoder_rerank(
    query_text: str,
    payloads: dict[str, str],
    top_k: int = 3,
    seed: int = 0,
) -> list[tuple[str, float]]:
    """
    模拟 BGE-Reranker Cross-Encoder 重排。
    真实场景：将 query_text 与每条 payload 做 cross attention，输出 logit 分数。
    Mock：基于字符串重叠度模拟相关性打分。
    """
    rng = random.Random(seed)
    query_tokens = set(query_text.lower().split())
    scores: list[tuple[str, float]] = []
    for cid, payload in payloads.items():
        payload_tokens = set(payload.lower().split())
        overlap = len(query_tokens & payload_tokens)
        # logit → sigmoid 归一化
        raw_logit = overlap / max(len(query_tokens), 1) + rng.uniform(0.0, 0.2)
        score = 1.0 / (1.0 + math.e ** (-raw_logit * 3))
        scores.append((cid, round(score, 4)))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


# ─── 核心算法：手写 RRF（倒数秩融合）────────────────────────────────────────

def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: int = 60,
) -> dict[str, float]:
    """
    倒数秩融合算法（Reciprocal Rank Fusion）。
    公式：RRF_score(d) = Σ 1/(k + rank_i(d))，k=60 为经验常数（Cormack 2009）。

    Args:
        ranked_lists: 多路召回结果，每路为按相关度排序的 candidate_id 列表。
        k: 平滑常数，防止低 rank 文档分数过于悬殊，建议 60。

    Returns:
        {candidate_id: rrf_score} 字典，已按分数降序排列。
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, candidate_id in enumerate(ranked, start=1):
            scores[candidate_id] = scores.get(candidate_id, 0.0) + 1.0 / (k + rank)
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))


def weighted_fusion(
    score_32: dict[str, float],
    score_128: dict[str, float],
    score_1024: dict[str, float],
    score_sparse: dict[str, float],
    w32: float = 0.15,
    w128: float = 0.25,
    w1024: float = 0.40,
    w_sparse: float = 0.20,
) -> dict[str, float]:
    """
    4 路 RRF 分数加权融合。
    权重来自方案文档：0.15·32D + 0.25·128D + 0.40·1024D + 0.20·sparse
    """
    all_ids = set(score_32) | set(score_128) | set(score_1024) | set(score_sparse)
    fused: dict[str, float] = {}
    for cid in all_ids:
        fused[cid] = (
            w32     * score_32.get(cid, 0.0)
            + w128  * score_128.get(cid, 0.0)
            + w1024 * score_1024.get(cid, 0.0)
            + w_sparse * score_sparse.get(cid, 0.0)
        )
    return dict(sorted(fused.items(), key=lambda x: x[1], reverse=True))


# ─── 主搜索端点 ───────────────────────────────────────────────────────────────

@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    """
    B 端混合检索主入口。
    完整链路：Filter → L1(32D) → L2(128D) → L3(1024D) → Sparse补漏 → RRF → Top30 → Rerank → TopK
    """
    t_start = time.perf_counter()
    session_id = str(uuid.uuid4())
    latencies: dict[str, float] = {}
    # 请求级种子：消除 payload fetch / rerank mock 对全局随机状态的依赖
    req_seed = hash(session_id)

    # ── Step 0: 意图降维（Query Parser）─────────────────────────────────────
    t0 = time.perf_counter()
    parsed = _mock_parse_query(req.query_text)
    latencies["query_parse_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # ── Step 1: Filter Gate（硬过滤，不调用向量索引）────────────────────────
    t0 = time.perf_counter()
    filtered_pool = _mock_filter_gate(_MOCK_CANDIDATES, req.filters)
    latencies["filter_gate_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # ── Step 2: 召回层 ────────────────────────────────────────────────────────
    t0 = time.perf_counter()

    # L1 与 Sparse 并发：两者均为独立 DB 查询，互不依赖
    l1_results, raw_sparse = await asyncio.gather(
        asyncio.to_thread(_mock_recall_l1, parsed["target_vec_32"], filtered_pool, 200),
        asyncio.to_thread(_mock_sparse_recall, parsed["extracted_tags"], filtered_pool, 40),
    )
    l1_ids = [c for c, _ in l1_results]

    # L2 仅在 L1 结果集上运行（缩小范围）
    l2_results = await asyncio.to_thread(
        _mock_recall_l2, parsed["target_vec_128"], l1_ids, 80
    )
    l2_ids = [c for c, _ in l2_results]

    # L3 仅在 L2 结果集上运行
    l3_results = await asyncio.to_thread(
        _mock_recall_l3, parsed["target_vec_1024"], l2_ids, 40
    )

    # 补漏过滤：只保留三层 dense 全集未覆盖的 sparse 候选人
    # dense 已覆盖的在 RRF 中已有分数，sparse 重复带入只是冗余噪声
    dense_covered: frozenset[str] = frozenset(
        c for c, _ in l1_results + l2_results + l3_results
    )
    sparse_results = [(c, r) for c, r in raw_sparse if c not in dense_covered]

    latencies["recall_layers_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # ── Step 3: RRF 倒数秩融合（纯内存计算，禁止调用大模型）────────────────
    t0 = time.perf_counter()
    rrf_32     = reciprocal_rank_fusion([[c for c, _ in l1_results]])
    rrf_128    = reciprocal_rank_fusion([[c for c, _ in l2_results]])
    rrf_1024   = reciprocal_rank_fusion([[c for c, _ in l3_results]])
    rrf_sparse = reciprocal_rank_fusion([[c for c, _ in sparse_results]])

    fused = weighted_fusion(rrf_32, rrf_128, rrf_1024, rrf_sparse)
    top30_ids = list(fused.keys())[:30]
    latencies["rrf_fusion_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # ── Step 4: 拉取 Rerank 弹药（仅 Top-30，此时才拉全量文本）────────────
    t0 = time.perf_counter()
    payloads = await asyncio.to_thread(_mock_fetch_reranker_payloads, top30_ids, req_seed)
    latencies["payload_fetch_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # ── Step 5: Cross-Encoder 重排（BGE-Reranker 深度注意力计算）───────────
    t0 = time.perf_counter()
    reranked = await asyncio.to_thread(
        _mock_cross_encoder_rerank, req.query_text, payloads, req.top_k, req_seed
    )
    latencies["rerank_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # ── 组装最终结果 ──────────────────────────────────────────────────────
    results: list[CandidateScore] = []
    for cid, rerank_score in reranked:
        rrf_score = fused.get(cid, 0.0)
        results.append(CandidateScore(
            candidate_id=cid,
            score_32=round(rrf_32.get(cid, 0.0), 5),
            score_128=round(rrf_128.get(cid, 0.0), 5),
            score_1024=round(rrf_1024.get(cid, 0.0), 5),
            score_sparse=round(rrf_sparse.get(cid, 0.0), 5),
            rrf_score=round(rrf_score, 5),
            rerank_score=rerank_score,
            final_score=round(0.4 * rrf_score + 0.6 * rerank_score, 5),
            matched_abilities=parsed["extracted_tags"][:3],
            reranker_payload=payloads.get(cid, ""),
        ))

    total_ms = round((time.perf_counter() - t_start) * 1000, 2)
    latencies["total_ms"] = total_ms

    if total_ms > 1500:
        logger.warning(
            "[search] session=%s latency=%.1fms exceeds 1500ms SLA", session_id, total_ms
        )

    return SearchResponse(
        session_id=session_id,
        query_text=req.query_text,
        total_latency_ms=total_ms,
        stage_latencies_ms=latencies,
        results=results,
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "heartcert-l9-search"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
