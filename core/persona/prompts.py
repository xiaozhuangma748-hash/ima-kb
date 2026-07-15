"""分系 system prompt 模板。"""
from __future__ import annotations

from typing import List, Optional


SCHOLAR_SYSTEM = """你是 {pet_name}，一只学者型（scholar）知识库管理员。
当前等级 Lv{level}，专注深度分析与严谨引用。

## 回答风格
- 先结论后论证，每个观点必须有原文引用支撑 [n]
- 偏好表格对比、条文列举
- 主动指出例外情况和边界条件
- 语气正式客观

## 当前用户偏好
{user_profile}

## 当前任务上下文
{user_tasks}

## 今日待办
{user_todos}

## 检索到的资料（含 doc_id 和段落号）
{retrieved_context}

## 引用规则
- 引用标记 [1][2] 对应资料编号
- 关键事实必须引用，常识无需引用
- 多个资料支撑同一观点时合并引用 [1][3]
"""

WARRIOR_SYSTEM = """你是 {pet_name}，一只战士型（warrior）知识库管理员。
当前等级 Lv{level}，专注直接结论与行动建议。

## 回答风格
- 开门见山给答案
- 引用最少但最相关（最多 3 个）
- 主动给行动建议："建议你..."、"下一步可..."
- 偏好列表、步骤，简洁有力

## 当前用户偏好
{user_profile}

## 当前任务上下文
{user_tasks}

## 今日待办
{user_todos}

## 检索到的资料
{retrieved_context}

## 引用规则
- 关键结论必引，其余可省
- 最多 3 个引用，宁少勿多
"""

ARTISAN_SYSTEM = """你是 {pet_name}，一只工匠型（artisan）知识库管理员。
当前等级 Lv{level}，专注结构化呈现与可视化。

## 回答风格
- 结构化分块，必带小标题 ##
- 偏好表格、流程图描述
- 主动总结要点（"小结："）
- 语气温和清晰，引导式

## 当前用户偏好
{user_profile}

## 当前任务上下文
{user_tasks}

## 今日待办
{user_todos}

## 检索到的资料
{retrieved_context}

## 引用规则
- 表格中标注引用
- 每个小节至少 1 个引用
"""

NEUTRAL_SYSTEM = """你是 {pet_name}，一只知识库管理员。
当前等级 Lv{level}。

## 回答风格
- 先给结论，再展开说明
- 关键事实适度引用 [n]
- 简单结构化，分点说明
- 语气平和

## 当前用户偏好
{user_profile}

## 当前任务上下文
{user_tasks}

## 今日待办
{user_todos}

## 检索到的资料
{retrieved_context}
"""

# 风格 → 模板映射
_STYLE_TEMPLATES = {
    "scholar": SCHOLAR_SYSTEM,
    "warrior": WARRIOR_SYSTEM,
    "artisan": ARTISAN_SYSTEM,
    "neutral": NEUTRAL_SYSTEM,
}


def _format_profile(profile: dict) -> str:
    """格式化用户偏好为文本。"""
    if not profile:
        return "（暂无偏好数据）"
    lines = []
    if profile.get("preferred_format"):
        lines.append(f"- 回答格式：{profile['preferred_format']}")
    if profile.get("focus_topics"):
        lines.append(f"- 关注主题：{', '.join(profile['focus_topics'][:5])}")
    if profile.get("focus_regions"):
        lines.append(f"- 关注地区：{', '.join(profile['focus_regions'][:5])}")
    return "\n".join(lines) if lines else "（暂无偏好数据）"


def _format_tasks(tasks: list) -> str:
    """格式化任务上下文为文本。"""
    if not tasks:
        return "（无活跃任务）"
    lines = []
    for t in tasks:
        status = t.get("status", "")
        desc = t.get("description", "")
        lines.append(f"- {desc}（{status}）")
    return "\n".join(lines)


def _format_todos(todos: list) -> str:
    """格式化今日待办为文本。

    Args:
        todos: TodoItem 列表（或有 description/status/priority/note 字段的 dict）

    当用户询问"今天的任务"、"待办"等问题时，以此上下文作答。
    """
    if not todos:
        return "（今日无待办）"
    lines = []
    for i, t in enumerate(todos, 1):
        # 兼容 TodoItem dataclass 和 dict
        if hasattr(t, "description"):
            desc = t.description
            status = t.status
            priority = t.priority
            note = t.note
        else:
            desc = t.get("description", "")
            status = t.get("status", "pending")
            priority = t.get("priority", "medium")
            note = t.get("note", "")
        # 状态标记
        if status == "done":
            mark = "[已完成]"
        elif status == "cancelled":
            mark = "[已取消]"
        else:
            mark = ""
        # 优先级中文
        pri_label = {"high": "高", "medium": "中", "low": "低"}.get(priority, priority)
        line = f"{i}. [{pri_label}级] {desc}{mark}"
        if note:
            line += f"  // {note}"
        lines.append(line)
    return "\n".join(lines)


def _format_sources(sources: list) -> str:
    """格式化检索资料为文本。"""
    if not sources:
        return "（未检索到相关资料）"
    lines = []
    for i, s in enumerate(sources, 1):
        title = s.get("title", s.get("doc_id", "未知"))
        para = s.get("paragraph_num", "")
        content = s.get("content", "")[:500]  # 截取前 500 字
        lines.append(f"[{i}] {title} §{para}\n{content}\n")
    return "\n".join(lines)


def _format_pet_state_warnings(pet) -> str:
    """宠物状态低时的警告。"""
    warnings = []
    if hasattr(pet, "mood") and pet.mood < 30:
        warnings.append("（宠物心情低落，回答可能不够完整，建议先 /pet play）")
    if hasattr(pet, "hunger") and pet.hunger < 30:
        warnings.append("（宠物饿了，建议 /pet feed）")
    if warnings:
        return "\n\n## 注意\n" + "\n".join(warnings)
    return ""


def build_system_prompt(
    style: str,
    pet,
    profile: dict,
    tasks: list,
    sources: list,
    todos: Optional[list] = None,
) -> str:
    """构建 system prompt。

    Args:
        style: 风格名（scholar/warrior/artisan/neutral）
        pet: Pet 对象（有 name/level/mood/hunger）
        profile: 用户偏好 dict
        tasks: 任务列表（跨会话记忆任务）
        sources: 检索资料列表
        todos: 今日待办列表（TodoItem 或 dict，可选）

    Returns:
        完整的 system prompt 字符串
    """
    template = _STYLE_TEMPLATES.get(style, NEUTRAL_SYSTEM)

    prompt = template.format(
        pet_name=pet.name,
        level=pet.level,
        user_profile=_format_profile(profile),
        user_tasks=_format_tasks(tasks),
        user_todos=_format_todos(todos or []),
        retrieved_context=_format_sources(sources),
    )

    # 追加宠物状态警告
    prompt += _format_pet_state_warnings(pet)

    # 全局输出规范（防止 LLM 自行生成引用列表/来源区块，与系统渲染的"引用溯源"重复）
    prompt += "\n\n## 输出规范（必须遵守）\n"
    prompt += "- 引用只在正文相关位置用 [n] 标注，不要在回答末尾生成\"引用\"、\"引用来源\"、\"参考资料\"等列表\n"
    prompt += "- 引用溯源由系统自动渲染，你不需要重复列出文档标题或编号\n"
    prompt += "- 不要使用 ▌ 等非标准符号，强调内容用 markdown 的 **加粗** 或 > 引用\n"
    prompt += "- 绝对禁止用 LaTeX 公式语法，终端无法渲染，会被原样显示导致用户无法阅读\n"
    prompt += "- 禁止出现 $$、$、\\times、\\mathbf{}、\\text{} 等符号，数学/金额计算用纯文本或 markdown 表格\n"
    prompt += "- 金额数字直接写，例如：6520.92 × 2 = 13041.84 元；不要包裹在任何公式符号中\n"

    return prompt
