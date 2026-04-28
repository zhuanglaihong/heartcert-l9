"""
Module: schemas/report_schema.py
Tests: 极客认证报告 Mock 工厂的动态性、防伪签名有效性、数据边界
"""

import hashlib
import hmac

import pytest
from schemas.report_schema import GeekCertReport, mock_report, _SIGNING_KEY, _sign


class TestMockReport:
    def test_returns_valid_model(self):
        report = mock_report()
        assert isinstance(report, GeekCertReport)

    def test_radar_chart_has_exactly_six_dimensions(self):
        report = mock_report()
        assert len(report.radar_chart) == 6

    def test_radar_scores_in_valid_range(self):
        report = mock_report()
        for dim in report.radar_chart:
            assert 0.0 <= dim.score <= 100.0
            assert 0.0 <= dim.percentile <= 100.0

    def test_vec_32_summary_length(self):
        report = mock_report()
        assert len(report.vec_32_summary) == 32
        for v in report.vec_32_summary:
            assert 0.0 <= v <= 1.0

    def test_anti_forgery_signature_verifiable(self):
        report = mock_report(candidate_id="test-c-001")
        stamp = report.anti_forgery
        expected_sig = _sign(stamp.cert_id, stamp.issued_at, report.candidate_id)
        assert stamp.signature == expected_sig

    def test_two_calls_produce_different_cert_ids(self):
        """Mock 工厂必须动态生成，禁止硬编码固定值。"""
        r1 = mock_report()
        r2 = mock_report()
        assert r1.cert_id != r2.cert_id

    def test_candidate_id_passed_through(self):
        cid = "fixed-candidate-abc"
        report = mock_report(candidate_id=cid)
        assert report.candidate_id == cid

    def test_combat_confidence_in_valid_range(self):
        report = mock_report()
        assert 0.0 <= report.combat_confidence <= 1.0

    def test_reranker_payload_not_empty(self):
        report = mock_report()
        assert len(report.reranker_payload) > 0

    def test_top_abilities_atom_ids_in_range(self):
        report = mock_report()
        for ability in report.top_abilities:
            assert 1 <= ability.atom_id <= 1024
