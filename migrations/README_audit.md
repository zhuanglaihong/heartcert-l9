# 老架构漏洞审计报告（Task 3 前置）

> 基于逐行阅读 `docs/schema.md` 得出，每条缺陷均标注具体表名和字段名。
> 本文档先于 DDL 交付，违反此顺序视为跳过架构审查。

---

## 缺陷 1：向量字段无维度约束——HNSW 索引语义失效

**涉及表/字段：**
- `candidates.skill_vector extensions.vector`（无 N）
- `candidates.assessment_embedding extensions.vector`（无 N）
- `candidates.resume_embedding extensions.vector`（无 N）
- `sub_skills.embedding extensions.vector`（无 N）

**缺陷本质：**
pgvector 的 `HNSW` / `IVFFlat` 索引在建立时须绑定固定维度 `vector(N)`。当字段类型为裸 `vector`（无括号 N）时，不同来源的 embedding 模型可以将任意维度的浮点数组无声插入同一列，导致：
1. 索引图结构在不同维度向量混入后发生语义错误，召回结果不可信。
2. 与 1024-atom 原子能力体系完全脱节——`skill_vector` 到底是 128D、512D 还是 1024D，数据库层面无任何保障。

**修正方向：** 所有向量字段必须声明 `vector(1024)`（原子层）、`vector(128)`（族层）、`vector(32)`（宏观层），并迁移至独立的 `candidate_vectors` 窄表。

---

## 缺陷 2：三路向量混嵌候选人主行——亿级召回内存爆炸

**涉及表/字段：** `candidates`（35+ 列，含 3 个向量字段在同一行）

**缺陷本质：**
PostgreSQL 执行 pgvector HNSW ANN 扫描时，以行为单位将数据从磁盘加载进 `shared_buffers`。`candidates` 主表每行除三个大向量外，还携带 `salary_expectations jsonb`、`industry_preferences jsonb`、`job_type_preferences jsonb`、`benefits_priority jsonb` 等多个 JSONB 字段，单行有效载荷极大。

亿级候选人规模下，每次向量召回的内存放大比约为 **8–15×**，极易触发 OOM 或导致 buffer pool thrashing，使向量搜索延迟从毫秒级退化至秒级。

**修正方向：** 向量字段剥离至独立的 `candidate_vectors(candidate_id PK, vec_32, vec_128, vec_1024)` 窄表，主表仅保留标量索引字段。

---

## 缺陷 3：`candidate_dimension_scores` 直接 UPSERT——评分无账本，不可追溯

**涉及表/字段：**
```sql
-- candidate_dimension_scores
constraint candidate_dimension_scores_pkey primary key (candidate_id, dim_id)
-- assessment_id 仅为外键引用，不参与主键
```

**缺陷本质：**
主键为 `(candidate_id, dim_id)`，意味着**同一候选人同一维度全局只保留最后一次分数**。当候选人完成第二次测评，新分数通过 `ON CONFLICT DO UPDATE` 覆盖旧值，第一次测评的贡献被永久抹除。

后果：
- 无法回答「哪次测评让这名候选人的算法维度从 0.6 跌到 0.4」
- 无法撤销错误的评分并重算
- 与新架构要求的「题目→能力贡献账本→候选人快照」链路完全不兼容

**修正方向：** 引入 `candidate_ability_contributions(candidate_id, assessment_id, ability_id, version, is_active)` 事件账本，`candidate_ability_snapshots` 作为派生快照，禁止直接覆写。

---

## 缺陷 4：`assessments` 是 35 列 God Table——JSONB 黑洞 + 无分区

**涉及表/字段：**
`assessments` 内含以下 JSONB 列（非完整列举）：
- `question_evaluations jsonb`
- `subskill_ratings jsonb`
- `dimension_scores jsonb`
- `dimension_details jsonb`
- `final_report_structured jsonb`
- `state_history jsonb`
- `interview_plan jsonb`
- `selected_scenarios jsonb`

**缺陷本质：**
6–8 个 JSONB 列共存于同一行，PostgreSQL TOAST 机制被迫将超出 2KB 阈值的列分页到 TOAST 表存储，每次 UPDATE 触发全行重写 + TOAST 重写，产生大量死行（dead tuple）。

无 `PARTITION BY RANGE(started_at)` 意味着：
1. autovacuum 需要对全量历史数据清理死行，在写入峰值期永久追不上。
2. 范围查询（如「过去 30 天的测评」）无法做分区裁剪，退化为全表扫描。
3. 单表 B-Tree 索引在亿级行后 I/O 放大严重。

**修正方向：** 将 JSONB 评分字段拆解为 `question_ability_scores`（原子账本）和 `assessment_ability_aggregates`（单场聚合），`assessments` 仅保留状态字段；高写日志表按月分区。

---

## 缺陷 5：`sub_skills` 无维度层级——1024 原子能力体系无法落地

**涉及表/字段：**
```sql
-- sub_skills
vector_index integer null,
constraint sub_skills_vector_index_key unique (vector_index)
-- 无 CHECK (vector_index BETWEEN 1 AND 1024)
-- 无 layer 字段（32 / 128 / 1024）
-- 无 parent_id 字段
```

**缺陷本质：**
`sub_skills` 是**开放集合**，可以任意增删，无法固化为「1024 个不可再分的原子能力」。`vector_index` 是普通整数，没有范围约束，即可写入 9999。

`dimension_skill_rel` 提供了「维度→子技能」的一层映射，但无法支持 `32D宏观层 → 128D族层 → 1024D原子层` 的三层向量汇聚。缺少 `ability_taxonomy_edges` 中的 `weight` 和 `rollup_mode`，三层向量的加权聚合根本无从实现。

**修正方向：** 新建 `ability_taxonomy_nodes(layer smallint CHECK (layer IN (32, 128, 1024)), atom_id SMALLINT CHECK (atom_id BETWEEN 1 AND 1024))` 和 `ability_taxonomy_edges(parent_id, child_id, weight)`，`sub_skills` 保留作为历史兼容层，新系统统一读能力树。

---

## 缺陷 6：高写日志表无分区——INSERT 路径竞争同一索引叶节点锁

**涉及表：** `api_usage_logs`、`page_events`、`user_activity_logs`

**缺陷本质：**
三张高频 append-only 表均无 `PARTITION BY RANGE(created_at)`。大量并发 INSERT 竞争同一 B-Tree 索引（如 `idx_api_usage_created`）的**最右叶节点**（right-most leaf），造成索引锁热点（index page latch contention）。在亿级日志写入场景下，INSERT 延迟可从微秒级升至数十毫秒，直接阻塞上游 API 响应链路。

**修正方向：** 按月（或按周）对上述三张表做 `PARTITION BY RANGE(created_at)`，每个分区独立维护最右索引叶节点，消除锁竞争。

---

## 缺陷 7：`vector_update_logs` 以 JSONB 存向量——类型逃逸 + 空间浪费

**涉及表/字段：**
```sql
previous_vector jsonb null,  -- 向量以文本 JSON 序列化
new_vector jsonb null,       -- 同上
```

**缺陷本质：**
`vector(N)` 二进制存储每维占 4 bytes（float32），1024 维向量 = 4096 bytes。
JSONB 存储同一向量时，每个浮点数序列化为文本（如 `0.123456789`），1024 维向量约占 **12–18KB**，存储放大 **3–5×**，且丧失类型安全——任何维度的向量均可写入，无法执行差值计算或余弦距离校验。

**修正方向：** `vector_update_logs` 废弃，向量版本历史由 `candidate_ability_contributions.version + is_active` 机制替代；如需留存快照，使用 `vector(1024)` 类型字段。

---

## 缺陷 8：`embedding_queue` 唯一约束引发并发重算竞争

**涉及表/字段：**
```sql
constraint embedding_queue_candidate_id_embedding_type_key unique (candidate_id, embedding_type)
```

**缺陷本质：**
每位候选人每种 embedding 类型全局只能有一条队列记录。当候选人完成新测评需要重新生成 `skill_vector` 时，必须先 DELETE 旧记录再 INSERT，高并发场景下产生 DELETE-INSERT race condition，或因事务隔离导致两个 worker 同时处理同一候选人的 embedding 任务，造成向量双写。

**修正方向：** 队列粒度改为 `(candidate_id, assessment_id, embedding_type)`，允许多条并存，由 worker 幂等消费；或改用 PostgreSQL `FOR UPDATE SKIP LOCKED` 悲观锁队列模式。

---

## 缺陷 9：`question_bank` 为静态模板，动态题目无稳定主键

**涉及表/字段：**
```sql
-- interview_interactions
question_id uuid null,  -- 可为 null！动态生成题无主键
constraint interview_interactions_question_id_fkey foreign key (question_id) references question_bank(id)
```

**缺陷本质：**
动态生成的题目（Battlefield Agent 捏造的残卷题）没有 `question_bank` 中的对应记录，因此 `question_id` 为 null。这意味着：
1. 无法将「这道题」绑定到「哪些原子能力 ID」（`question_ability_bindings` 的前提是题有主键）。
2. 事后无法追溯「某道题考察了哪个 atom_id，权重是多少」。
3. Oracle Judge 的评分结果无法精确溯源到具体题目，能力向量的可信度存疑。

**修正方向：** 新建 `assessment_question_instances(id UUID PK, assessment_id, source_question_bank_id nullable, question_payload jsonb)`，动态生成题即时实例化并获得主键，`question_ability_bindings` 引用此表。

---

## 迁移策略（平滑双写，不切断线上读路径）

```
Step 1: 新建 12 张新表（ability_taxonomy_*, candidate_vectors 等），不修改任何老表
Step 2: 评分链路双写：旧表继续写，新表同步写（保证线上不中断）
Step 3: 回填历史 assessments → candidate_ability_contributions
Step 4: 从 candidate_ability_snapshots 重新生成三层向量写入 candidate_vectors
Step 5: 新搜索 pipeline 灰度上线，A/B 对比旧搜索
Step 6: 稳定后将 candidates.skill_vector / assessment_embedding 降级为兼容字段（保留但不写入）
```
