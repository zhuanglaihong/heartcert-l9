# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 项目背景

**系统名称：** 归心 HeartCert L9
**核心目标：** 将静态题库全面迁移至 AI 动态出题 + 原子能力落盘 + B 端工业级混合检索的全链路闭环。
**技术栈：** Python FastAPI + Supabase PostgreSQL (pgvector)
**环境管理：** uv（`pyproject.toml`）

---

## 交付标准（180 分钟计时，始于 2026-04-28）

| 任务 | 权重 | 交付文件 |
|------|------|----------|
| Task 1：4 个 Agent System Prompt | 30% | `agents/*.py` |
| Task 2：状态机工作流 + 极客认证报告 Schema | 20% | `workflow/state_machine.py`, `schemas/` |
| Task 3：老架构漏洞审计 + 新 DDL | 20% | `migrations/README_audit.md`, `migrations/*.sql` |
| Task 4：FastAPI 混合检索管线 | 30% | `search_pipeline.py` |

**评分红线：**
- Prompt 充斥套话 → 扣分
- Task 3 未先出漏洞审计直接写 DDL → 扣分
- 超时 → 扣分

---

## 常用命令

```bash
uv run uvicorn search_pipeline:app --reload   # 启动搜索管线
uv run pytest tests/ -v                       # 运行测试
uv add <package>                              # 添加依赖
uv sync                                       # 同步虚拟环境
```

---

## 核心架构

### 4 个 Agent 职责

| Agent | 输入 | 输出 |
|-------|------|------|
| **Ingestion Agent** | 原始简历文本 + 岗位选择 | `Candidate_DNA.json`（原子能力稀疏映射） |
| **Battlefield Agent** | `Candidate_DNA` + `Role_Blueprint` | 归心私有 RPC 框架残卷（含死锁/内存泄漏） |
| **X-RAG Agent** | WebSocket 代码 Diff / 语音文本流 | 弹窗异常追问（防抖触发，非 Diff 频率驱动） |
| **Oracle Judge Agent** | `Role_Schemas` + `Battle_Log` | 三位一体数据包（见下方格式） |

Oracle Judge 输出必须通过 Pydantic 强验证，格式固定为：

```json
{
  "judge_result": {
    "vector_updates": [{"atom_id": 145, "score": 0.85, "rationale": "..."}],
    "verified_skills": ["Golang", "Redis"],
    "reranker_payload": "150词以内核心战役摘要",
    "combat_confidence": 0.88
  }
}
```

### 三层向量架构

```
32D  → 宏观维度粗召回    → ability_taxonomy_nodes (layer=32)
128D → 能力族中召回      → ability_taxonomy_nodes (layer=128)
1024D→ 原子能力精召回    → ability_library (ID 0001-1024)
```

存储在 `candidate_vectors` 表（三字段分离，不混合）。

### 混合检索管线（延迟 ≤ 1.5s）

```
Filter Gate（城市/薪资/经验硬过滤）
    ↓
L1 粗召回  32D  →  top 200   search_candidates_by_vec32()
    ↓
L2 中召回 128D  →  top 80    search_candidates_by_vec128()（仅在 L1 结果集上）
    ↓
L3 精召回 1024D →  top 40    search_candidates_by_vec1024() + sparse GIN 补漏
    ↓
RRF 融合（k=60）→  top 30
权重：0.15·score32 + 0.25·score128 + 0.40·score1024 + 0.20·sparse
    ↓
Cross-Encoder Rerank（BGE-Reranker，喂入 reranker_payload）→ Top 3
```

RRF 公式：`score(d) = 1/(60 + rank_sparse) + 1/(60 + rank_dense)`

### L9 战役状态机（FSM）

```
PROVISIONING → COMBAT_ACTIVE → EVALUATING → CERTIFIED
                                           → FAILED
```

- `PROVISIONING` 超时 >15s → 降级到静态 `Fallback_Blueprint`

---

## 工程纪律（硬性约束，违反即扣分或线上崩溃）

1. **禁止引入 Elasticsearch**，底层必须 PostgreSQL 一体化打穿。
2. **禁止动态字符串作为能力标签**，必须使用 `ability_library.atom_id`（0001-1024）。
3. **X-RAG 禁止由 Diff 频率驱动**，必须 Debounce（建议触发条件：测试用例失败 Error Log 或 5 分钟重构增量）。
4. **RRF 层禁止调用大模型**，禁止拉取全量 JSONB，只传 `(candidate_id, rank)` 对。
5. **Oracle Judge 禁止自由打分**，只对 `Role_Schemas` 规定的原子 ID 打 0.0-1.0 分。
6. **向量写入必须保留账本**，禁止直接 UPDATE `candidate_vectors` 而不写 `candidate_ability_contributions`。
7. **1024 维向量必须平滑化**，未考核能力赋基线微小权重（≈0.01），非绝对 0，避免维度诅咒。
8. **向量引入时间衰减因子** λ，实际召回分 = 余弦相似度 × e^(-λΔt)，Δt 为距最后一次 L9 战役的月数。

---

## Task 3：老架构漏洞（必须在新 DDL 之前列出）

审查 `docs/schema.md` 中 51 张老表，以下是系统性缺陷：

1. **向量维度失配**：老 `candidates` 向量维度非 1024D，无法对齐 `ability_library` 原子 ID 体系。
2. **HNSW 参数缺失**：现有向量索引未指定 `m`/`ef_construction`，高并发下 IVFFlat 性能劣化，召回精度不稳定。
3. **无表分区**：`assessments`/`candidates` 亿级规模无 Range/Hash 分区策略，顺序扫描拖垮高并发写入。
4. **无事件账本**：评分直接 UPDATE 覆写，`candidate_ability_contributions` 缺失，无法回放/追溯/重算任一能力分。
5. **三层向量缺失**：只有单一向量字段，32D/128D/1024D 分层召回路由无法实现。
6. **JSONB 无 GIN 索引**：`profile_data` 未建 GIN 索引，BM25 稀疏召回退化为全表扫描。
7. **无时间衰减机制**：向量缺 `last_certified_at` 字段，三年前的 1.0 与今日 1.0 等权参与召回，精度严重失真。

新 DDL 见 `migrations/001_new_tables.sql` + `migrations/002_indexes_hnsw.sql`。

---

## 数据库约定

- 主键：`UUID DEFAULT gen_random_uuid()`
- 向量索引：**HNSW**（禁用 IVFFlat），`m=16, ef_construction=64`，`vector_cosine_ops`
- 稀疏文本：`GIN` 索引 + `JSONB` `profile_data`
- 时间字段：`TIMESTAMPTZ`
- 新表清单：`ability_taxonomy_nodes`, `ability_taxonomy_edges`, `assessment_question_instances`, `question_ability_bindings`, `question_ability_scores`, `assessment_ability_aggregates`, `candidate_ability_snapshots`, `candidate_ability_contributions`, `candidate_vectors`, `job_requirement_profiles`, `search_sessions`, `search_candidate_scores`

---

## 文件结构速查

```
agents/
  ingestion_agent.py      # Task 1: 简历解析 → Candidate_DNA
  battlefield_agent.py    # Task 1: 沙盒战役渲染
  xrag_agent.py           # Task 1: 实时异常追问
  oracle_judge_agent.py   # Task 1: 受控向量评分输出
workflow/
  state_machine.py        # Task 2: FSM + 熔断机制
schemas/
  agent_contracts.py      # Task 2: Agent I/O Pydantic 合约
  report_schema.py        # Task 2: 极客认证报告 JSON Schema
migrations/
  README_audit.md         # Task 3: 老架构漏洞审计（必须先于 DDL）
  001_new_tables.sql      # Task 3: 12 张新表
  002_indexes_hnsw.sql    # Task 3: HNSW + GIN 索引
search_pipeline.py        # Task 4: FastAPI 混合检索（Mock DB + 手写 RRF）
docs/
  schema.md               # 现有 51 张老表 DDL（参考用）
  出题和检索重构方案.md    # 架构方案原文
  方案设计.md             # PRD + 12 张新表定义
```
