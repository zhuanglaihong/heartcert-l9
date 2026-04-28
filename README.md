# HeartCert L9 — AI 动态出题与 B 端混合检索全链路重构

> 从传统静态题库，向 AI 根据候选人简历与子能力动态定制出题、原子能力高维资产落盘、再到 B 端双轨混合检索的工业级全链路闭环。

**技术栈：** Python FastAPI · Supabase PostgreSQL · pgvector · uv

---

## 架构概览

```
简历 + 岗位
    │
    ▼
┌─────────────────┐
│  Ingestion Agent │  简历 → Candidate_DNA.json（1024 原子能力稀疏映射）
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│  Battlefield Agent   │  DNA → 归心私有 RPC 框架残卷（含嵌入式 bug）
└────────┬────────────┘
         │
         ▼
┌─────────────────┐
│   X-RAG Agent   │  WebSocket Diff → 防抖触发 → 异常注入追问
└────────┬────────┘
         │
         ▼
┌──────────────────────┐
│  Oracle Judge Agent   │  Battle_Log → 1024D 向量 + verified_skills + reranker_payload
└────────┬─────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────┐
│  Hybrid Search Pipeline (B 端)                          │
│  Filter → L1(32D,200) → L2(128D,80) → L3(1024D,40)    │
│  → RRF 融合 → Top30 → Cross-Encoder Rerank → Top3      │
└────────────────────────────────────────────────────────┘
```

---

## 快速启动

```bash
# 安装依赖（需要 uv）
uv sync

# 启动混合检索 API
uv run uvicorn search_pipeline:app --reload

# 测试搜索端点
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query_text": "需要能处理 Redis 分布式死锁的 Golang 后端", "top_k": 3}'

# 运行测试
uv run pytest tests/ -v
```

---

## 项目结构

```
├── agents/
│   ├── ingestion_agent.py      # Task 1：简历解析 → Candidate_DNA
│   ├── battlefield_agent.py    # Task 1：沙盒战役渲染（虚构框架 + 嵌入式 bug）
│   ├── xrag_agent.py           # Task 1：防抖实时异常追问
│   └── oracle_judge_agent.py   # Task 1：受控 1024D 向量输出
├── workflow/
│   └── state_machine.py        # Task 2：L9 战役 FSM + 熔断机制
├── schemas/
│   ├── agent_contracts.py      # Task 2：4 Agent 的 Pydantic I/O 合约
│   └── report_schema.py        # Task 2：极客认证报告 Schema + Mock 工厂
├── migrations/
│   ├── README_audit.md         # Task 3：老架构 9 条系统性缺陷审计
│   ├── 001_new_tables.sql      # Task 3：12 张新表 DDL
│   └── 002_indexes_hnsw.sql    # Task 3：HNSW 向量索引 + GIN 索引
├── search_pipeline.py          # Task 4：FastAPI 混合检索（手写 RRF）
└── docs/
    ├── schema.md               # 现有 51 张老表 DDL（参考）
    ├── 出题和检索重构方案.md    # 架构方案原文
    └── 方案设计.md             # PRD + 12 张新表定义
```

---

## Task 说明

### Task 1 · Agent System Prompts（30%）

4 个 Agent 均具备强约束控制：

| Agent | 核心约束 |
|-------|---------|
| **Ingestion** | 只提取，不推断；atom_id 必须来自 ability_library(0001-1024)；有 evidence_quote 才能打分 |
| **Battlefield** | 框架名完全虚构；bug 必须真实存在于代码中；禁止注释提示 bug 位置 |
| **X-RAG** | 仅响应测试失败或 5 分钟 Checkpoint；注入环境故障而非概念题；每次只出一问 |
| **Oracle Judge** | 只对 role_schema.atom_ids 评分；rationale 必须引用 battle_log 具体事件；reranker_payload ≤ 150 词 |

### Task 2 · 工作流编排与 Schema（20%）

- **L9 战役 FSM**：`PROVISIONING → COMBAT_ACTIVE → EVALUATING → CERTIFIED/FAILED`
- **熔断机制**：PROVISIONING 超时 15s 自动降级到 Fallback_Blueprint；EVALUATING 超时 60s 标记 FAILED
- **极客认证报告**：6 维雷达图 + HMAC-SHA256 防伪签名，Mock 数据完全动态生成

### Task 3 · 存量架构重构（20%）

老架构 9 条系统性缺陷（详见 `migrations/README_audit.md`）：

1. 向量字段无维度约束（`extensions.vector` 无 N）
2. 三路向量混嵌候选人主行，亿级召回内存爆炸
3. `candidate_dimension_scores` 直接 UPSERT，评分无账本
4. `assessments` 35 列 God Table，6 个 JSONB 黑洞无分区
5. `sub_skills` 无维度层级，1024 原子体系无法落地
6. 高写日志表无分区，INSERT 竞争同一索引叶节点锁
7. `vector_update_logs` 以 JSONB 存向量，3-5x 空间浪费
8. `embedding_queue` 唯一约束引发并发重算竞争
9. `question_bank` 静态模板，动态题目无稳定主键

新 DDL 引入 12 张新表，三层向量分离存储，HNSW 索引参数明确（m=16, ef_construction=64）。

### Task 4 · 混合检索管线（30%）

```
RRF 公式：score(d) = Σ 1/(60 + rank_i(d))

权重融合：final = 0.15·score_32 + 0.25·score_128 + 0.40·score_1024 + 0.20·sparse

延迟 SLA：≤ 1500ms（Mock 环境实测 ~3ms）
```

全部 DB 调用使用 Mock 函数，可直接运行无需数据库连接。

---

## 工程纪律

- 禁止引入 Elasticsearch，底层必须 PostgreSQL 一体化打穿
- X-RAG 禁止由 Diff 频率驱动，必须防抖
- RRF 层禁止调用大模型，禁止拉取全量 JSONB
- 1024D 向量必须平滑化（未考核能力赋基线微小权重，非绝对 0）
- 向量写入必须保留 contribution 账本，禁止直接 UPDATE candidate_vectors
