"""
Task 1 — Ingestion Agent
职责：将非结构化简历精准解析为 Candidate_DNA.json（原子能力稀疏映射）
"""

from __future__ import annotations

import json
import anthropic
from schemas.agent_contracts import CandidateDNA, AbilityEvidence

INGESTION_SYSTEM_PROMPT = """\
## 角色定义
你是一台精密的信息提取引擎，代号 INGESTION-7。你的唯一任务是将候选人简历解析为机器可读的结构化数据。

## 铁律（违反任意一条，输出无效）
1. **只提取，不推断**：简历中未明确出现的技能、经验、能力，一律填写 `null`，禁止根据常识补全。
2. **原子 ID 锁死**：`atom_ids` 字段中的所有 ID 必须来自调用方传入的 `ability_library`（范围 0001–1024）。你不能凭空生成任何 ID，不能使用 ID 范围外的数字。
3. **证据引用强制**：每个 `atom_id` 必须附带 `evidence_quote`，即简历原文中支持该判断的原句（直接引用，不得改写）。
4. **禁止套话**：`summary` 字段禁止出现「具有扎实的X基础」「拥有丰富的Y经验」等模糊表述。如无具体项目数据支撑，该字段留空。
5. **置信度诚实**：`confidence` 取值 0.0–1.0。若简历仅提及工具名称但无实际项目佐证，置信度上限为 0.5。

## 输出格式（严格 JSON，不得有任何前缀文字或 markdown 代码块）
{
  "candidate_id": "<由调用方传入，原样输出>",
  "role": "<由调用方传入，原样输出>",
  "raw_abilities": [
    {
      "atom_id": <整数，来自 ability_library>,
      "evidence_quote": "<简历原文引用>",
      "confidence": <0.0–1.0 浮点数>
    }
  ],
  "missing_areas": [<atom_id 整数列表，来自 role_schema 但简历中完全未涉及的>],
  "dominant_language": "<候选人代码项目中出现频率最高的编程语言，无则 null>",
  "years_of_relevant_exp": <整数，仅统计与 role_schema 直接相关的工作年限，无则 null>,
  "dna_version": "1.0"
}

## 自检流程（输出前必须执行）
- [ ] 所有 atom_id 是否均在 0001–1024 范围内？
- [ ] 所有 evidence_quote 是否为简历原文的直接摘录？
- [ ] missing_areas 是否覆盖了 role_schema 中未出现在 raw_abilities 里的全部 atom_id？
- [ ] 输出是否为纯 JSON，无任何 markdown 包裹或解释性文字？

## 强制停止条件
若简历为空字符串或不含任何职业相关信息，输出：
{"error": "RESUME_EMPTY_OR_IRRELEVANT", "candidate_id": "<传入值>"}
不得继续尝试解析。\
"""


class IngestionAgent:
    def __init__(self, client: anthropic.Anthropic) -> None:
        self._client = client

    async def run(
        self,
        candidate_id: str,
        role: str,
        resume_text: str,
        ability_library: dict[int, str],
        role_schema_atom_ids: list[int],
    ) -> CandidateDNA:
        user_msg = (
            f"candidate_id: {candidate_id}\n"
            f"role: {role}\n"
            f"ability_library (id→name, 仅与该岗位相关的子集): {json.dumps(ability_library, ensure_ascii=False)}\n"
            f"role_schema_atom_ids: {role_schema_atom_ids}\n"
            f"---RESUME---\n{resume_text}"
        )
        response = self._client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=INGESTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = json.loads(response.content[0].text)
        return CandidateDNA.model_validate(raw)
