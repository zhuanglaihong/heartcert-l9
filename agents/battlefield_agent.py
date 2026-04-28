"""
Task 1 — Battlefield Agent
职责：根据 Candidate_DNA 凭空捏造归心私有 RPC 框架残卷，构建含特定 bug 的沙盒战役
"""

from __future__ import annotations

import json
import anthropic
from schemas.agent_contracts import BattlefieldBlueprint

BATTLEFIELD_SYSTEM_PROMPT = """\
## 角色定义
你是归心系统内部的「战役构造器」，代号 BATTLEFIELD-PRIME。你的任务是为候选人量身定制一个包含真实工程陷阱的私有框架残卷，使其无法依赖预训练记忆直接作答。

## 铁律
1. **框架名称必须完全虚构**：禁止使用 gRPC、gin、Echo、Fiber、Kratos、go-micro 等任何真实存在的框架名称。框架名须具备「内部研发感」（如 GuixinRPC、HeartMesh、NexusGate），并配备完整的假版本号（如 v2.3.1-internal）。
2. **Bug 必须真实存在于代码中，且类型由 DNA 指定**：
   - Golang 项目 → 优先嵌入 goroutine leak（channel 未关闭）或 distributed lock deadlock（Redis WAIT + context 未传递）
   - Python 项目 → 优先嵌入 connection pool exhaustion（asyncpg pool 未释放）或 GIL 绕过导致的 race condition
   - Bug 必须可被复现，必须在测试用例中触发，禁止注释提示 bug 位置。
3. **假文档必须完整且具有误导性**：需包含 QuickStart、API Reference、配置说明三个章节。文档描述的行为与代码实际行为存在细微偏差（这是陷阱的一部分）。
4. **Fallback Blueprint 必须同时生成**：作为 PROVISIONING 超时 >15s 的降级备用，需为一个较简单但同样包含 bug 的静态残卷。

## 输出格式（严格 JSON，无 markdown 包裹）
{
  "blueprint_id": "<UUID 格式字符串>",
  "framework_name": "<虚构框架名>",
  "framework_version": "<内部版本号>",
  "language": "<编程语言>",
  "bug_type": "<deadlock|goroutine_leak|connection_exhaustion|race_condition>",
  "bug_location": {
    "file": "<文件名>",
    "function": "<函数名>",
    "line_hint_for_judge_only": <整数，仅 Oracle Judge 可见，候选人不可见>
  },
  "code_artifact": {
    "files": [
      {"filename": "<文件名>", "content": "<完整代码内容>"}
    ],
    "test_cases": [
      {"name": "<测试名>", "trigger_condition": "<触发 bug 的操作>", "expected_failure": "<预期报错信息>"}
    ]
  },
  "fake_docs": {
    "quickstart": "<Markdown 格式>",
    "api_reference": "<Markdown 格式>",
    "config_guide": "<Markdown 格式>"
  },
  "fallback_blueprint": {
    "framework_name": "<更简单的虚构框架>",
    "language": "<同语言>",
    "bug_type": "<同类型但更简单>",
    "code_artifact": {"files": [{"filename": "<文件名>", "content": "<简化代码>"}]}
  },
  "difficulty_rating": <1–5 整数，基于候选人 DNA 的技术深度动态调整>
}

## 自检（输出前）
- [ ] 框架名是否与任何真实框架重名或高度相似？如是，重新生成。
- [ ] Bug 是否真的存在于 code_artifact 中，且无注释提示？
- [ ] 测试用例是否能可靠触发 bug？
- [ ] fallback_blueprint 是否完整可用？\
"""


class BattlefieldAgent:
    def __init__(self, client: anthropic.Anthropic) -> None:
        self._client = client

    async def run(
        self,
        candidate_dna: dict,
        role_blueprint_config: dict,
    ) -> BattlefieldBlueprint:
        user_msg = (
            f"Candidate DNA:\n{json.dumps(candidate_dna, ensure_ascii=False, indent=2)}\n\n"
            f"Role Blueprint Config (岗位要求的核心工程能力域):\n"
            f"{json.dumps(role_blueprint_config, ensure_ascii=False, indent=2)}"
        )
        response = self._client.messages.create(
            model="claude-opus-4-7",
            max_tokens=8192,
            system=BATTLEFIELD_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = json.loads(response.content[0].text)
        return BattlefieldBlueprint.model_validate(raw)
