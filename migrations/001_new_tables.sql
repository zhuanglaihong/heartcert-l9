-- ============================================================
-- Task 3 — 新架构 12 张核心表 DDL
-- 基于 docs/方案设计.md，修正老架构 9 项系统性缺陷
-- 迁移策略：先建新表，双写过渡，禁止直接修改老表（见 README_audit.md）
-- ============================================================

-- 前置：确认 pgvector 插件已启用（Supabase 默认已安装）
CREATE EXTENSION IF NOT EXISTS vector;


-- ────────────────────────────────────────────────────────────
-- 0. ability_library
--    1024 个不可再分的原子能力静态底座（绝对不变表，只通过迁移脚本维护）。
--    atom_id 是全系统能力体系的唯一锚点：
--      - Agent 合约中的 AbilityEvidence.atom_id 引用此表
--      - Oracle Judge 输出的 dense_vector_1024 的维度位置即 atom_id - 1
--      - ability_taxonomy_nodes（1024层）通过 atom_id 与此表关联
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.ability_library (
    atom_id     SMALLINT    PRIMARY KEY CHECK (atom_id BETWEEN 1 AND 1024),
    skill_name  VARCHAR(64) UNIQUE NOT NULL,
    domain      VARCHAR(32) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 此表为只读静态表，禁止业务代码直接 INSERT/UPDATE，只允许迁移脚本维护
COMMENT ON TABLE public.ability_library IS
    '1024 原子能力静态底座。只读，由迁移脚本维护，禁止业务代码写入。';


-- ────────────────────────────────────────────────────────────
-- 1. ability_taxonomy_nodes
--    统一能力树，替代旧 dimensions + sub_skills 的双轨结构。
--    layer 严格限制为 32 / 128 / 1024 三层，禁止随意添加层级。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.ability_taxonomy_nodes (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ability_code    TEXT        UNIQUE NOT NULL,           -- 如 "GOLANG.CONCURRENCY.GOROUTINE_LEAK"
    ability_name    TEXT        NOT NULL,
    layer           SMALLINT    NOT NULL CHECK (layer IN (32, 128, 1024)),
    parent_id       UUID        REFERENCES public.ability_taxonomy_nodes(id) ON DELETE RESTRICT,
    vector_index    INT         NOT NULL,                  -- 在对应层向量中的位置索引（0-based）
    -- atom_id 仅 layer=1024 节点设置，与 ability_library 对齐（atom_id = vector_index + 1）
    -- 是 Oracle Judge integer atom_id ↔ UUID ability_id 的桥接列
    atom_id         SMALLINT    REFERENCES public.ability_library(atom_id) ON DELETE RESTRICT,
    status          TEXT        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deprecated')),
    metadata        JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_vector_index_by_layer CHECK (
        (layer = 32   AND vector_index BETWEEN 0 AND 31)  OR
        (layer = 128  AND vector_index BETWEEN 0 AND 127) OR
        (layer = 1024 AND vector_index BETWEEN 0 AND 1023)
    ),
    -- layer=1024 节点必须有 atom_id，其他层不得有 atom_id
    CONSTRAINT chk_atom_id_only_for_leaf CHECK (
        (layer = 1024 AND atom_id IS NOT NULL) OR
        (layer IN (32, 128) AND atom_id IS NULL)
    ),
    CONSTRAINT chk_atom_id_matches_vector_index CHECK (
        atom_id IS NULL OR atom_id = vector_index + 1
    )
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_nodes_layer
    ON public.ability_taxonomy_nodes (layer);
CREATE INDEX IF NOT EXISTS idx_taxonomy_nodes_parent
    ON public.ability_taxonomy_nodes (parent_id)
    WHERE parent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_taxonomy_nodes_status
    ON public.ability_taxonomy_nodes (status)
    WHERE status = 'active';


-- ────────────────────────────────────────────────────────────
-- 2. ability_taxonomy_edges
--    显式描述 1024→128、128→32 的汇聚权重关系。
--    rollup_mode 控制聚合算法，当前只支持 weighted_mean。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.ability_taxonomy_edges (
    parent_id   UUID            NOT NULL REFERENCES public.ability_taxonomy_nodes(id) ON DELETE CASCADE,
    child_id    UUID            NOT NULL REFERENCES public.ability_taxonomy_nodes(id) ON DELETE CASCADE,
    weight      NUMERIC(6, 5)   NOT NULL CHECK (weight > 0 AND weight <= 1),
    rollup_mode TEXT            NOT NULL DEFAULT 'weighted_mean' CHECK (rollup_mode IN ('weighted_mean', 'max', 'min')),
    PRIMARY KEY (parent_id, child_id)
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_edges_child
    ON public.ability_taxonomy_edges (child_id);


-- ────────────────────────────────────────────────────────────
-- 3. assessment_question_instances
--    动态生成的题目必须实例化，获得稳定主键，解决老架构缺陷 9。
--    source_question_bank_id 为 NULL 表示完全动态生成（非静态题库题）。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.assessment_question_instances (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id             UUID        NOT NULL REFERENCES public.assessments(id) ON DELETE CASCADE,
    source_question_bank_id   UUID        REFERENCES public.question_bank(id) ON DELETE SET NULL,
    question_type             TEXT        NOT NULL CHECK (question_type IN ('code_sandbox', 'prd_battle', 'interview', 'written')),
    round_no                  INT         NOT NULL CHECK (round_no >= 1),
    difficulty_level          NUMERIC(4, 2) NOT NULL DEFAULT 1.0 CHECK (difficulty_level BETWEEN 0.1 AND 5.0),
    generation_prompt_version TEXT,
    question_payload          JSONB       NOT NULL DEFAULT '{}',
    status                    TEXT        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'skipped', 'cancelled')),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_question_instances_assessment
    ON public.assessment_question_instances (assessment_id);
CREATE INDEX IF NOT EXISTS idx_question_instances_type
    ON public.assessment_question_instances (assessment_id, question_type);


-- ────────────────────────────────────────────────────────────
-- 4. question_ability_bindings
--    题目→原子能力的映射账本，权重和应趋近 1.0（允许微小误差）。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.question_ability_bindings (
    question_instance_id UUID            NOT NULL REFERENCES public.assessment_question_instances(id) ON DELETE CASCADE,
    ability_id           UUID            NOT NULL REFERENCES public.ability_taxonomy_nodes(id) ON DELETE CASCADE,
    layer                SMALLINT        NOT NULL DEFAULT 1024 CHECK (layer IN (32, 128, 1024)),
    weight               NUMERIC(6, 5)   NOT NULL CHECK (weight > 0 AND weight <= 1),
    binding_source       TEXT            NOT NULL CHECK (binding_source IN ('llm_generated', 'rule_mapped', 'human_reviewed')),
    confidence           NUMERIC(6, 5)   NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (question_instance_id, ability_id)
);

CREATE INDEX IF NOT EXISTS idx_qab_ability
    ON public.question_ability_bindings (ability_id);


-- ────────────────────────────────────────────────────────────
-- 5. question_ability_scores
--    原子级评分账本，解决老架构缺陷 3（UPSERT 覆写无法追溯）。
--    这是最关键的原始事实表，任何能力分值均可追溯到此。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.question_ability_scores (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    question_instance_id UUID           NOT NULL REFERENCES public.assessment_question_instances(id) ON DELETE CASCADE,
    assessment_id       UUID            NOT NULL REFERENCES public.assessments(id) ON DELETE CASCADE,
    candidate_id        UUID            NOT NULL REFERENCES public.candidates(id) ON DELETE CASCADE,
    ability_id          UUID            NOT NULL REFERENCES public.ability_taxonomy_nodes(id) ON DELETE CASCADE,
    raw_score           NUMERIC(5, 2)   NOT NULL CHECK (raw_score BETWEEN 0 AND 100),
    normalized_score    NUMERIC(6, 5)   NOT NULL CHECK (normalized_score BETWEEN 0 AND 1),
    weight              NUMERIC(6, 5)   NOT NULL CHECK (weight > 0 AND weight <= 1),
    contribution_score  NUMERIC(8, 5)   NOT NULL,  -- normalized_score * weight
    score_source        TEXT            NOT NULL CHECK (score_source IN ('ai_grader', 'objective_rule', 'human_override')),
    grader_version      TEXT,
    evidence            JSONB           NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qas_assessment
    ON public.question_ability_scores (assessment_id);
CREATE INDEX IF NOT EXISTS idx_qas_candidate_ability
    ON public.question_ability_scores (candidate_id, ability_id);
CREATE INDEX IF NOT EXISTS idx_qas_ability
    ON public.question_ability_scores (ability_id);


-- ────────────────────────────────────────────────────────────
-- 6. assessment_ability_aggregates
--    单场测评内聚合后的能力值（非全局快照）。
--    recomputed_at 用于幂等重算触发判断。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.assessment_ability_aggregates (
    assessment_id       UUID            NOT NULL REFERENCES public.assessments(id) ON DELETE CASCADE,
    candidate_id        UUID            NOT NULL REFERENCES public.candidates(id) ON DELETE CASCADE,
    ability_id          UUID            NOT NULL REFERENCES public.ability_taxonomy_nodes(id) ON DELETE CASCADE,
    layer               SMALLINT        NOT NULL CHECK (layer IN (32, 128, 1024)),
    aggregation_mode    TEXT            NOT NULL DEFAULT 'weighted_mean',
    score               NUMERIC(6, 5)   NOT NULL CHECK (score BETWEEN 0 AND 1),
    support_count       INT             NOT NULL DEFAULT 0,
    support_weight      NUMERIC(8, 5)   NOT NULL DEFAULT 0,
    source_question_count INT           NOT NULL DEFAULT 0,
    recomputed_at       TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (assessment_id, ability_id)
);

CREATE INDEX IF NOT EXISTS idx_aaa_candidate
    ON public.assessment_ability_aggregates (candidate_id);
CREATE INDEX IF NOT EXISTS idx_aaa_ability_layer
    ON public.assessment_ability_aggregates (ability_id, layer);


-- ────────────────────────────────────────────────────────────
-- 7. candidate_ability_snapshots
--    候选人当前能力画像（快照，非唯一事实来源）。
--    由 candidate_ability_contributions 重算得出，禁止直接写入。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.candidate_ability_snapshots (
    candidate_id        UUID            NOT NULL REFERENCES public.candidates(id) ON DELETE CASCADE,
    ability_id          UUID            NOT NULL REFERENCES public.ability_taxonomy_nodes(id) ON DELETE CASCADE,
    layer               SMALLINT        NOT NULL CHECK (layer IN (32, 128, 1024)),
    score               NUMERIC(6, 5)   NOT NULL CHECK (score BETWEEN 0 AND 1),
    aggregation_mode    TEXT            NOT NULL DEFAULT 'mean_of_assessments',
    assessment_count    INT             NOT NULL DEFAULT 0,
    last_assessment_id  UUID            REFERENCES public.assessments(id) ON DELETE SET NULL,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (candidate_id, ability_id)
);

CREATE INDEX IF NOT EXISTS idx_cas_candidate_layer
    ON public.candidate_ability_snapshots (candidate_id, layer);


-- ────────────────────────────────────────────────────────────
-- 8. candidate_ability_contributions
--    跨场次贡献账本，支持撤销和重算（version + is_active 机制）。
--    解决老架构缺陷 3 的根本方案。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.candidate_ability_contributions (
    candidate_id    UUID            NOT NULL REFERENCES public.candidates(id) ON DELETE CASCADE,
    assessment_id   UUID            NOT NULL REFERENCES public.assessments(id) ON DELETE CASCADE,
    ability_id      UUID            NOT NULL REFERENCES public.ability_taxonomy_nodes(id) ON DELETE CASCADE,
    layer           SMALLINT        NOT NULL CHECK (layer IN (32, 128, 1024)),
    score           NUMERIC(6, 5)   NOT NULL CHECK (score BETWEEN 0 AND 1),
    weight          NUMERIC(8, 5)   NOT NULL DEFAULT 1.0,
    version         INT             NOT NULL DEFAULT 1,
    is_active       BOOLEAN         NOT NULL DEFAULT true,
    -- grader_version 记录评分时使用的 Oracle Judge 版本，便于线上排错与回溯
    grader_version  TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (candidate_id, assessment_id, ability_id, version)
);

CREATE INDEX IF NOT EXISTS idx_cac_candidate_active
    ON public.candidate_ability_contributions (candidate_id, is_active)
    WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_cac_assessment
    ON public.candidate_ability_contributions (assessment_id);


-- ────────────────────────────────────────────────────────────
-- 9. candidate_vectors
--    三层向量分离存储，解决老架构缺陷 1 和缺陷 2。
--    不再将向量混嵌在 candidates 主行中。
--    last_certified_at 支持时间衰减因子计算。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.candidate_vectors (
    candidate_id        UUID        PRIMARY KEY REFERENCES public.candidates(id) ON DELETE CASCADE,
    ability_vec_32      vector(32),
    ability_vec_128     vector(128),
    ability_vec_1024    vector(1024),
    vec_version         TEXT        NOT NULL DEFAULT '1.0',
    last_certified_at   TIMESTAMPTZ,  -- 用于时间衰减因子 e^(-λΔt)
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ────────────────────────────────────────────────────────────
-- 10. job_requirement_profiles
--     B 端每次搜索固化为 profile，支持重放和权重调整。
--     三层目标向量对齐 candidate_vectors 的三层结构。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.job_requirement_profiles (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                  UUID        REFERENCES public.employer_jobs(id) ON DELETE SET NULL,
    query_text              TEXT        NOT NULL,
    query_text_clean        TEXT,
    target_vec_32           vector(32),
    target_vec_128          vector(128),
    target_vec_1024         vector(1024),
    ability_weights         JSONB       NOT NULL DEFAULT '{}',  -- {ability_id: weight}
    must_have_abilities     JSONB       NOT NULL DEFAULT '[]',  -- [ability_id, ...]
    nice_to_have_abilities  JSONB       NOT NULL DEFAULT '[]',
    llm_parse_payload       JSONB       NOT NULL DEFAULT '{}',
    created_by              UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jrp_job
    ON public.job_requirement_profiles (job_id)
    WHERE job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jrp_created_by
    ON public.job_requirement_profiles (created_by, created_at DESC);


-- ────────────────────────────────────────────────────────────
-- 11. search_sessions
--     每次 B 端搜索请求记录，关联 requirement_profile，支持重放。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.search_sessions (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    requirement_profile_id  UUID        NOT NULL REFERENCES public.job_requirement_profiles(id) ON DELETE CASCADE,
    filters                 JSONB       NOT NULL DEFAULT '{}',  -- 硬过滤条件快照
    mode                    TEXT        NOT NULL DEFAULT 'hybrid' CHECK (mode IN ('hybrid', 'vector_only', 'sparse_only')),
    recall_plan             JSONB       NOT NULL DEFAULT '{}',  -- L1/L2/L3 召回参数快照
    rerank_model            TEXT,
    created_by              UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_sessions_profile
    ON public.search_sessions (requirement_profile_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_sessions_created_by
    ON public.search_sessions (created_by, created_at DESC);


-- ────────────────────────────────────────────────────────────
-- 12. search_candidate_scores
--     每次搜索的候选人分层得分记录，支持链路日志分析。
--     可回答：「某候选人在哪层被召回/淘汰，得分是多少」。
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.search_candidate_scores (
    search_session_id   UUID            NOT NULL REFERENCES public.search_sessions(id) ON DELETE CASCADE,
    candidate_id        UUID            NOT NULL REFERENCES public.candidates(id) ON DELETE CASCADE,
    -- 三层向量得分（对应 L1/L2/L3 召回层）
    score_32            NUMERIC(6, 5),
    score_128           NUMERIC(6, 5),
    score_1024          NUMERIC(6, 5),
    -- GIN BM25 稀疏路得分（补漏路径）
    score_sparse        NUMERIC(6, 5),
    -- 硬过滤满足度（城市/薪资/经验，0/1 或连续值）
    score_filter        NUMERIC(6, 5),
    -- 四路 RRF 融合得分（进 rerank 前的中间态，用于链路审计）
    rrf_score           NUMERIC(8, 7),
    -- Cross-Encoder 重排得分
    score_rerank        NUMERIC(6, 5),
    final_score         NUMERIC(6, 5),
    -- 各层召回/淘汰原因，回答「某候选人在哪层被淘汰」
    explanations        JSONB           NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (search_session_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS idx_scs_session_score
    ON public.search_candidate_scores (search_session_id, final_score DESC);
