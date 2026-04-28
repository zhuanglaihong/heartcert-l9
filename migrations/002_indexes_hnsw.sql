-- ============================================================
-- Task 3 — HNSW 向量索引 + 补充 GIN 索引
-- 修正老架构缺陷 1（向量无维度约束）和缺陷 6（GIN 缺失）
-- 参数选择依据：
--   m=16, ef_construction=64 为 pgvector 官方推荐起始值，
--   平衡召回精度（recall@10 ≈ 0.97）与构建时间。
--   高精度场景可升至 m=32, ef_construction=128，但构建时间 4x。
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- candidate_vectors — 三层 HNSW 索引（向量从主表剥离后，只扫窄表）
-- 修正老架构缺陷 2：向量混嵌主行的内存放大问题
-- ────────────────────────────────────────────────────────────

-- L1 粗召回（32 维）
CREATE INDEX IF NOT EXISTS idx_cv_vec32_hnsw
    ON public.candidate_vectors
    USING hnsw (ability_vec_32 vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- L2 中召回（128 维）
CREATE INDEX IF NOT EXISTS idx_cv_vec128_hnsw
    ON public.candidate_vectors
    USING hnsw (ability_vec_128 vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- L3 精召回（1024 维）— 高维场景可适当提升 ef_construction
CREATE INDEX IF NOT EXISTS idx_cv_vec1024_hnsw
    ON public.candidate_vectors
    USING hnsw (ability_vec_1024 vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- ────────────────────────────────────────────────────────────
-- job_requirement_profiles — 三层目标向量 HNSW 索引
-- ────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_jrp_vec32_hnsw
    ON public.job_requirement_profiles
    USING hnsw (target_vec_32 vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_jrp_vec128_hnsw
    ON public.job_requirement_profiles
    USING hnsw (target_vec_128 vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_jrp_vec1024_hnsw
    ON public.job_requirement_profiles
    USING hnsw (target_vec_1024 vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- ────────────────────────────────────────────────────────────
-- candidates — 补充 profile_data GIN 索引（BM25 稀疏召回路径）
-- 修正老架构缺陷 6：JSONB 无 GIN，稀疏召回退化为全表扫描
-- 注：profile_data 字段需在 candidates 表上补充（或在 candidate_vectors 表上新增）
-- ────────────────────────────────────────────────────────────

-- 若 candidates 表尚无 profile_data JSONB 字段，先 ALTER TABLE 添加
ALTER TABLE public.candidates
    ADD COLUMN IF NOT EXISTS profile_data JSONB NOT NULL DEFAULT '{}';

-- 对 profile_data 建 GIN 索引，支持 @> 操作符的 BM25 匹配
CREATE INDEX IF NOT EXISTS idx_candidates_profile_gin
    ON public.candidates
    USING GIN (profile_data);

-- verified_skills 是 JSONB 数组，->> 返回 JSON 序列化文本（含方括号和引号），
-- 必须用 jsonb_to_tsvector 才能正确拆解数组元素为词典。
CREATE INDEX IF NOT EXISTS idx_candidates_verified_skills_fts
    ON public.candidates
    USING GIN (
        jsonb_to_tsvector('simple', COALESCE(profile_data->'verified_skills', '[]'::jsonb), '["string"]')
    );


-- ────────────────────────────────────────────────────────────
-- candidate_vectors — last_certified_at 索引（时间衰减因子查询）
-- 时间衰减公式：actual_score = cosine × e^(-λΔt)，需高效过滤近期认证候选人
-- ────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_cv_last_certified
    ON public.candidate_vectors (last_certified_at DESC NULLS LAST)
    WHERE last_certified_at IS NOT NULL;


-- ────────────────────────────────────────────────────────────
-- candidate_ability_contributions — 按 (candidate_id, ability_id) 快速重算快照
-- 重做某 assessment 时，只需重算受影响候选人的特定 ability，此索引避免全表扫
-- ────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_cac_candidate_ability_active
    ON public.candidate_ability_contributions (candidate_id, ability_id)
    WHERE is_active = true;


-- ────────────────────────────────────────────────────────────
-- ability_taxonomy_nodes — atom_id 快速查找（Oracle Judge integer→UUID 桥接）
-- ────────────────────────────────────────────────────────────
CREATE UNIQUE INDEX IF NOT EXISTS idx_taxonomy_nodes_atom_id
    ON public.ability_taxonomy_nodes (atom_id)
    WHERE atom_id IS NOT NULL;


-- ────────────────────────────────────────────────────────────
-- 高写日志表分区迁移建议（注释形式，需在维护窗口执行）
-- 修正老架构缺陷 6：无分区导致 INSERT 锁竞争
-- ────────────────────────────────────────────────────────────

-- Step 1: 创建分区父表（重命名旧表）
-- ALTER TABLE public.api_usage_logs RENAME TO api_usage_logs_legacy;
-- CREATE TABLE public.api_usage_logs (LIKE api_usage_logs_legacy INCLUDING ALL)
--     PARTITION BY RANGE (created_at);
--
-- Step 2: 创建月分区
-- CREATE TABLE public.api_usage_logs_2026_04
--     PARTITION OF public.api_usage_logs
--     FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
--
-- Step 3: 迁移历史数据（在低峰期批量 INSERT INTO ... SELECT）
-- INSERT INTO public.api_usage_logs SELECT * FROM api_usage_logs_legacy;
--
-- 同理对 page_events、user_activity_logs 执行相同操作。


-- ────────────────────────────────────────────────────────────
-- 验证 HNSW 索引是否正确创建
-- ────────────────────────────────────────────────────────────
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename IN ('candidate_vectors', 'job_requirement_profiles')
--   AND indexdef LIKE '%hnsw%';
