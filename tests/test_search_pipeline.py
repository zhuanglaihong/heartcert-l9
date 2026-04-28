"""
Module: search_pipeline.py
Tests: 手写 RRF 算法正确性、分层召回结构、端到端 /search 响应
"""

import pytest
from fastapi.testclient import TestClient

from search_pipeline import app, reciprocal_rank_fusion, weighted_fusion

client = TestClient(app)


# ─── RRF 算法单元测试 ─────────────────────────────────────────────────────────

class TestRRF:
    def test_single_list_score_formula(self):
        """score(d) = 1/(60 + rank)，rank 从 1 开始"""
        result = reciprocal_rank_fusion([["a", "b", "c"]], k=60)
        assert abs(result["a"] - 1 / 61) < 1e-9
        assert abs(result["b"] - 1 / 62) < 1e-9
        assert abs(result["c"] - 1 / 63) < 1e-9

    def test_multi_list_accumulates_scores(self):
        """出现在多路结果中的文档，分数应累加"""
        result = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)
        # b 在第一路 rank=2，第二路 rank=1
        expected_b = 1 / 62 + 1 / 61
        assert abs(result["b"] - expected_b) < 1e-9

    def test_higher_rank_means_higher_score(self):
        result = reciprocal_rank_fusion([["best", "mid", "worst"]], k=60)
        assert result["best"] > result["mid"] > result["worst"]

    def test_result_sorted_descending(self):
        result = reciprocal_rank_fusion([["x", "y", "z"], ["z", "x", "y"]], k=60)
        scores = list(result.values())
        assert scores == sorted(scores, reverse=True)

    def test_empty_list_returns_empty(self):
        assert reciprocal_rank_fusion([]) == {}

    def test_candidate_only_in_one_list(self):
        """仅出现在一路的候选人也应被正确记录"""
        result = reciprocal_rank_fusion([["a"], ["b"]], k=60)
        assert "a" in result
        assert "b" in result

    def test_k_affects_score_magnitude(self):
        """k 越大，分数越小（平滑效果越强）"""
        r_small_k = reciprocal_rank_fusion([["a"]], k=10)
        r_large_k = reciprocal_rank_fusion([["a"]], k=100)
        assert r_small_k["a"] > r_large_k["a"]


class TestWeightedFusion:
    def test_weights_sum_to_one(self):
        """默认权重 0.15+0.25+0.40+0.20=1.0"""
        total = 0.15 + 0.25 + 0.40 + 0.20
        assert abs(total - 1.0) < 1e-9

    def test_fusion_score_bounded(self):
        """最大分数不超过各路 RRF 最大分数的加权上界"""
        s32 = {"a": 0.5}
        s128 = {"a": 0.5}
        s1024 = {"a": 0.5}
        sparse = {"a": 0.5}
        result = weighted_fusion(s32, s128, s1024, sparse)
        # 0.15*0.5 + 0.25*0.5 + 0.40*0.5 + 0.20*0.5 = 0.5
        assert abs(result["a"] - 0.5) < 1e-9

    def test_missing_candidate_in_some_lists_gets_zero_contribution(self):
        result = weighted_fusion({"a": 1.0}, {}, {}, {})
        assert abs(result["a"] - 0.15) < 1e-9  # 只有 w32=0.15 贡献


# ─── /search 端到端测试 ───────────────────────────────────────────────────────

class TestSearchEndpoint:
    def test_returns_200(self):
        resp = client.post("/search", json={"query_text": "Redis 死锁 Golang", "top_k": 3})
        assert resp.status_code == 200

    def test_returns_correct_result_count(self):
        resp = client.post("/search", json={"query_text": "并发控制", "top_k": 3})
        data = resp.json()
        assert len(data["results"]) == 3

    def test_top_k_respected(self):
        for k in [1, 2, 5]:
            resp = client.post("/search", json={"query_text": "Python 异步", "top_k": k})
            assert len(resp.json()["results"]) == k

    def test_response_has_required_fields(self):
        resp = client.post("/search", json={"query_text": "test", "top_k": 1})
        data = resp.json()
        assert "session_id" in data
        assert "total_latency_ms" in data
        assert "stage_latencies_ms" in data
        assert "results" in data

    def test_result_has_all_score_fields(self):
        resp = client.post("/search", json={"query_text": "test", "top_k": 1})
        result = resp.json()["results"][0]
        for field in ["score_32", "score_128", "score_1024", "score_sparse", "rrf_score", "rerank_score", "final_score"]:
            assert field in result

    def test_final_score_in_valid_range(self):
        resp = client.post("/search", json={"query_text": "test", "top_k": 3})
        for r in resp.json()["results"]:
            assert 0.0 <= r["final_score"] <= 1.0

    def test_health_endpoint(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_query_too_short_rejected(self):
        """min_length=2，单字符查询应被 FastAPI 以 422 拒绝"""
        resp = client.post("/search", json={"query_text": "x", "top_k": 3})
        assert resp.status_code == 422
