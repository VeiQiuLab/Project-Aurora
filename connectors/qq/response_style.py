"""QQ-only response presentation guidance and conservative output cleanup."""

import re

from modules.chat import DEFAULT_SYSTEM_CONTEXT


QQ_CHANNEL_INSTRUCTION = """你正在 QQ 即时聊天中回复。
默认使用自然、口语化、简洁的中文，像正常聊天一样连续表达，不要写成文章、报告或说明书。

除非对方明确要求：
- 不使用标题
- 不使用 Markdown 粗体
- 不使用项目符号或编号列表
- 不一句话单独占一行
- 不使用表格
- 不使用总结式章节结构

普通回复优先使用 1～2 个自然段；简单问题通常 1～4 句话即可。
可以使用表情，但应克制，默认最多 0～1 个 emoji，不要每句话都带表情。
不要频繁使用“具体来说”“以下是”“我会努力成为你的”“总的来说”等报告式模板语言。
如果用户明确要求步骤、清单、代码或详细说明，则允许使用必要的结构化格式。"""

QQ_GROUP_EXTRA = "群聊中请进一步简洁，除非对方明确要求，不要展开成长篇说明。"


def build_qq_system_context(*, is_group=False):
    instruction = QQ_CHANNEL_INSTRUCTION
    if is_group:
        instruction += "\n" + QQ_GROUP_EXTRA
    return f"{DEFAULT_SYSTEM_CONTEXT}\n\n{instruction}"


def normalize_qq_reply(text):
    """Only normalize excessive blank lines; preserve markdown, code, and lists."""
    return re.sub(r"\n{3,}", "\n\n", str(text or "")).strip()

