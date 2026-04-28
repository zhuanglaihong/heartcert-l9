# HeartCert L9 — AI 动态出题与 B 端混合检索全链路重构

**技术栈：** Python FastAPI · Supabase PostgreSQL · pgvector · uv  
**测试：** `52 passed` · `uv run pytest tests/ -v`

---

## 交付清单（对应评分标准）

| 交付物 | 文件 | 说明 |
|--------|------|------|
| **Prompt** | [`agents/ingestion_agent.py`](agents/ingestion_agent.py) | Ingestion Agent System Prompt |
| **Prompt** | [`agents/battlefield_agent.py`](agents/battlefield_agent.py) | Battlefield Agent System Prompt |
| **Prompt** | [`agents/xrag_agent.py`](agents/xrag_agent.py) | X-RAG Agent System Prompt |
| **Prompt** | [`agents/oracle_judge_agent.py`](agents/oracle_judge_agent.py) | Oracle Judge Agent System Prompt |
| **工作流说明** | [`workflow/state_machine.py`](workflow/state_machine.py) | FSM 状态机 + 熔断机制 + Agent 编排伪代码 |
| **Schema** | [`schemas/agent_contracts.py`](schemas/agent_contracts.py) | 4 Agent 的 Pydantic I/O 合约 |
| **Schema** | [`schemas/geek_cert_report.schema.json`](schemas/geek_cert_report.schema.json) | 极客认证报告 JSON Schema |
| **Schema** | [`schemas/geek_cert_report.example.json`](schemas/geek_cert_report.example.json) | 动态 Mock 示例（含雷达图 + 防伪签名） |
| **SQL（老架构审计）** | [`migrations/README_audit.md`](migrations/README_audit.md) | **先于 DDL 交付**：9 条系统性缺陷，指向具体表/字段 |
| **SQL（新 DDL）** | [`migrations/001_new_tables.sql`](migrations/001_new_tables.sql) | 12 张新表（含 FK 约束优化、平滑迁移注释） |
| **SQL（索引）** | [`migrations/002_indexes_hnsw.sql`](migrations/002_indexes_hnsw.sql) | HNSW 三层向量索引 + GIN 稀疏索引 |
| **Python 脚本** | [`search_pipeline.py`](search_pipeline.py) | FastAPI 混合检索全链路（手写 RRF + L1/L2/L3） |
| **测试** | [`tests/`](tests/) | 4 模块共 52 个测试用例，全部通过 |

---

## Task 1 · Agent System Prompts（30%）

每个 Prompt 均有**编号铁律**、**强制 JSON 格式**、**自检清单**，无套话。

### Ingestion Agent（简历解析）
> `agents/ingestion_agent.py` — `INGESTION_SYSTEM_PROMPT`

```
铁律：
1. 只提取，不推断——简历未出现的字段填 null，禁止根据常识补全
2. atom_ids 只能来自 ability_library（0001–1024），禁止自创
3. 每个 atom_id 必须附 evidence_quote（简历原文引用）
4. confidence > 0.5 须有项目数据佐证，否则上限 0.5
5. 输出纯 JSON，无任何 markdown 包裹
```

### Battlefield Agent（场景生成）
> `agents/battlefield_agent.py` — `BATTLEFIELD_SYSTEM_PROMPT`

```
铁律：
1. 框架名必须完全虚构（禁用 gRPC/gin/Echo 等真实框架）
2. bug 必须真实存在于代码中，禁止注释提示 bug 位置
3. 假文档需包含 QuickStart/API Reference/配置说明，且与代码行为有细微偏差
4. 必须同时生成 fallback_blueprint（PROVISIONING 超时降级用）
```

### X-RAG Agent（动态追问）
> `agents/xrag_agent.py` — `XRAG_SYSTEM_PROMPT`

```
铁律：
1. 只响应 test_failure Error Log 或 5 分钟 Checkpoint，禁止由 Diff 频率驱动
2. 追问必须模拟外部系统故障（Redis 宕机/连接池耗尽），禁止提概念题
3. 必须指向具体文件名 + 函数名，禁止泛问
4. 每次只出一问，禁止连发
```

### Oracle Judge Agent（确权决策）
> `agents/oracle_judge_agent.py` — `ORACLE_JUDGE_SYSTEM_PROMPT`

```
铁律：
1. 只对 role_schema.atom_ids 列表中的 ID 打分，库外 ID 禁止出现
2. rationale 必须引用 battle_log 具体事件（含时间戳/事件 ID）
3. reranker_payload ≤ 150 词
4. combat_confidence = min(1.0, actual_time / expected_time)，不得主观估值
5. 未被战役覆盖的 atom_id 分数必须为 0.0，禁止推测
```

---

## Task 2 · 工作流编排与 Schema（20%）

### 状态机（`workflow/state_machine.py`）

```
PROVISIONING ──[BLUEPRINT_READY]──→ COMBAT_ACTIVE
PROVISIONING ──[BLUEPRINT_TIMEOUT]─→ COMBAT_ACTIVE（used_fallback=True）
PROVISIONING ──[CHEAT_DETECTED]───→ FAILED
COMBAT_ACTIVE ─[BATTLE_COMPLETE]──→ EVALUATING
COMBAT_ACTIVE ─[CHEAT_DETECTED]───→ FAILED
EVALUATING ────[JUDGE_COMPLETE]───→ CERTIFIED
EVALUATING ────[JUDGE_TIMEOUT]────→ FAILED

熔断：PROVISIONING 超时 15s → 自动降级 Fallback_Blueprint
熔断：EVALUATING   超时 60s → FAILED
```

### 极客认证报告 Schema（`schemas/geek_cert_report.schema.json`）

核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `cert_id` | UUID | 证书唯一标识 |
| `radar_chart` | Array[6] | 6 维雷达图（系统设计/并发控制/故障降级/代码质量/调试能力/架构判断） |
| `top_abilities` | Array | 战役中验证的原子能力列表（atom_id + score + evidence） |
| `anti_forgery.signature` | string | HMAC-SHA256 防伪签名（cert_id:issued_at:candidate_id） |
| `vec_32_summary` | Array[32] | 32 维宏观向量摘要，用于前端可视化 |
| `reranker_payload` | string | ≤150 词战役摘要，B 端检索弹药 |

→ 查看完整 Mock 示例：[`schemas/geek_cert_report.example.json`](schemas/geek_cert_report.example.json)

---

## Task 3 · 存量架构重构（20%）

### 老架构 9 条系统性缺陷（`migrations/README_audit.md`）

> 基于逐行阅读 `docs/schema.md` 得出，每条均标注具体表名和字段名：

| # | 缺陷 | 涉及表/字段 |
|---|------|------------|
| 1 | 向量字段无维度约束，HNSW 索引语义失效 | `candidates.skill_vector`、`sub_skills.embedding`（均为裸 `extensions.vector`） |
| 2 | 三路向量混嵌主行，亿级召回内存爆炸（8–15× 放大） | `candidates`（35+ 列含 3 个大向量） |
| 3 | 直接 UPSERT 覆写，评分无账本不可追溯 | `candidate_dimension_scores`（主键 `(candidate_id, dim_id)`） |
| 4 | 35 列 God Table，6 个 JSONB 黑洞无分区 | `assessments.question_evaluations/subskill_ratings/dimension_scores` 等 |
| 5 | 无维度层级，1024 原子体系无法落地 | `sub_skills.vector_index`（无 CHECK/无 parent_id/无 layer） |
| 6 | 高写日志表无分区，INSERT 竞争索引叶节点锁 | `api_usage_logs`、`page_events`、`user_activity_logs` |
| 7 | 以 JSONB 存向量，3–5× 空间浪费 + 类型逃逸 | `vector_update_logs.previous_vector / new_vector` |
| 8 | 唯一约束引发并发重算竞争 | `embedding_queue` UNIQUE `(candidate_id, embedding_type)` |
| 9 | 静态题库无稳定主键，动态题目无法绑定原子能力 | `interview_interactions.question_id NULL` |

### 新 DDL 要点（`migrations/001_new_tables.sql` + `migrations/002_indexes_hnsw.sql`）

- **12 张新表**：`ability_taxonomy_nodes/edges`、`assessment_question_instances`、`question_ability_bindings/scores`、`assessment_ability_aggregates`、`candidate_ability_snapshots/contributions`、`candidate_vectors`、`job_requirement_profiles`、`search_sessions`、`search_candidate_scores`
- **三层向量分离**：`candidate_vectors(vec_32 vector(32), vec_128 vector(128), vec_1024 vector(1024))`
- **HNSW 参数明确**：`USING hnsw (...) WITH (m=16, ef_construction=64)`
- **平滑迁移**：先建新表双写，不切断线上读路径（见 SQL 内注释）

---

## Task 4 · 混合检索管线（30%）

> `search_pipeline.py` — FastAPI，全量 Mock DB，可直接运行

### 检索链路

```
POST /search
    │
    ├─ Query Parser → target_vec_32/128/1024 + extracted_tags
    ├─ Filter Gate  → 城市/薪资/经验硬过滤（→ ~400 候选人）
    │
    ├─ L1 粗召回   32D  HNSW → top 200
    ├─ L2 中召回  128D  HNSW → top 80   (仅在 L1 结果集上)
    ├─ L3 精召回 1024D  HNSW → top 40   (仅在 L2 结果集上)
    ├─ Sparse 补漏  GIN BM25 → top 40   (补 L1-L3 未覆盖)
    │
    ├─ RRF 融合（手写，k=60）→ top 30
    │     score(d) = Σ 1/(60 + rank_i(d))
    │     权重：0.15·32D + 0.25·128D + 0.40·1024D + 0.20·sparse
    │
    ├─ 拉取 reranker_payload（仅 top 30，避免 OOM）
    ├─ Cross-Encoder Rerank → top K
    │
    └─ 返回 SearchResponse（含各层分数 + 延迟分解）
```

### 快速验证

```bash
uv sync
uv run uvicorn search_pipeline:app --reload

curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query_text": "需要能处理 Redis 分布式死锁的 Golang 后端", "top_k": 3}'
```

---

## 运行测试

```bash
uv run pytest tests/ -v
# 52 passed in ~1.4s

# 覆盖模块：
# tests/test_agent_contracts.py  — Pydantic 约束校验（atom_id 范围、重复检测、score 精度）
# tests/test_report_schema.py    — Mock 工厂动态性、防伪签名可验证性
# tests/test_state_machine.py    — FSM 转换合法性、熔断边界
# tests/test_search_pipeline.py  — RRF 公式正确性、分层召回、端到端 /search
```

---

## 工程纪律（来自方案文档的硬性约束）

- 禁止引入 Elasticsearch，底层 PostgreSQL 一体化打穿
- X-RAG 禁止由 Diff 频率驱动，必须 Debounce
- RRF 层禁止调用大模型，禁止拉取全量 JSONB（先 RRF 出 Top-30，再拉 payload）
- Oracle Judge 只对 `role_schema.atom_ids` 评分，禁止自由发挥
- 1024D 向量必须平滑化（未考核能力赋基线微小权重，避免维度诅咒）
- 向量写入必须保留 `candidate_ability_contributions` 账本，禁止直接覆写
