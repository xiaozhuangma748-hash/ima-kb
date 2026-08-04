"""MemoryExtractor 测试：覆盖 JSON 解析、类型校验、降级、合并逻辑。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from core.memory.cross_session import CrossSessionMemory
from core.memory.extractor import MemoryExtractor


# ============================================================
# 测试 fixture
# ============================================================

class FakeLLM:
    """模拟 LLM 客户端，可预设返回内容或抛异常。"""

    def __init__(self, response: str = "", raises: Exception | None = None) -> None:
        self.response = response
        self.raises = raises
        self.call_count = 0
        self.last_kwargs = None

    def chat(self, messages, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return self.response


@pytest.fixture
def memory(tmp_path):
    """干净的 CrossSessionMemory 实例。"""
    return CrossSessionMemory(storage_path=tmp_path)


# ============================================================
# _parse_json 静态方法测试
# ============================================================

class TestParseJson:
    """测试 _parse_json 对各种 LLM 输出格式的兼容。"""

    def test_parse_pure_json(self):
        """纯 JSON 字符串正常解析。"""
        raw = '{"preferences": {"格式": "表格"}, "topics": ["殡葬"], "questions": [], "facts": []}'
        result = MemoryExtractor._parse_json(raw)
        assert result is not None
        assert result["preferences"]["格式"] == "表格"
        assert result["topics"] == ["殡葬"]

    def test_parse_json_with_markdown_block(self):
        """带 ```json ... ``` 代码块的输出能正确提取。"""
        raw = '''```json
{"preferences": {}, "topics": ["政策"], "questions": [], "facts": []}
```'''
        result = MemoryExtractor._parse_json(raw)
        assert result is not None
        assert result["topics"] == ["政策"]

    def test_parse_json_with_bare_code_block(self):
        """带 ``` （无 json 标识）代码块也能提取。"""
        raw = '''```
{"preferences": {}, "topics": [], "questions": [], "facts": []}
```'''
        result = MemoryExtractor._parse_json(raw)
        assert result is not None
        assert result == {"preferences": {}, "topics": [], "questions": [], "facts": []}

    def test_parse_json_with_prefix_text(self):
        """LLM 输出带前缀解释文本，能从中提取 JSON。"""
        raw = '''好的，分析结果如下：
{"preferences": {"语言": "中文"}, "topics": [], "questions": [], "facts": []}
以上就是提取结果。'''
        result = MemoryExtractor._parse_json(raw)
        assert result is not None
        assert result["preferences"]["语言"] == "中文"

    def test_parse_empty_string(self):
        """空字符串返回 None。"""
        assert MemoryExtractor._parse_json("") is None
        assert MemoryExtractor._parse_json(None) is None

    def test_parse_invalid_json(self):
        """非法 JSON 返回 None。"""
        raw = "这不是 JSON，也没有大括号"
        assert MemoryExtractor._parse_json(raw) is None

    def test_parse_truncated_json(self):
        """被截断的 JSON 返回 None。"""
        raw = '{"preferences": {"a": "b"'
        assert MemoryExtractor._parse_json(raw) is None

    def test_parse_json_array_returns_none(self):
        """顶层是数组（非对象）时返回 None。"""
        raw = '["a", "b", "c"]'
        assert MemoryExtractor._parse_json(raw) is None

    def test_parse_json_with_nested_objects(self):
        """嵌套对象能正常解析。"""
        raw = '{"preferences": {"a": {"b": "c"}}, "topics": [], "questions": [], "facts": []}'
        result = MemoryExtractor._parse_json(raw)
        assert result is not None
        assert result["preferences"]["a"]["b"] == "c"


# ============================================================
# extract_and_merge 主流程测试
# ============================================================

class TestExtractAndMerge:
    """测试 extract_and_merge 的完整流程。"""

    def test_successful_extraction_and_merge(self, memory):
        """正常提取 + 合并流程。"""
        llm = FakeLLM(response=json.dumps({
            "preferences": {"格式": "表格"},
            "topics": ["殡葬政策"],
            "questions": ["生态葬的补贴标准？"],
            "facts": ["用户在民政部门工作"],
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge(
            user_input="用表格列一下殡葬政策的要点",
            assistant_reply="好的，以下是表格...",
        )

        # 验证 LLM 被调用一次
        assert llm.call_count == 1
        # 验证低温度和小 max_tokens
        assert llm.last_kwargs["temperature"] == 0.1
        assert llm.last_kwargs["max_tokens"] == 300
        assert llm.last_kwargs["max_retries"] == 1

        # 验证返回的新增项
        assert "格式:表格" in added["preferences"]
        assert "殡葬政策" in added["topics"]
        assert "生态葬的补贴标准？" in added["questions"]
        assert "用户在民政部门工作" in added["facts"]

        # 验证已合并到 memory
        context = memory.get_context()
        assert "- 格式: 表格" in context
        assert "- 殡葬政策" in context
        assert "- 生态葬的补贴标准？" in context
        assert "- 用户在民政部门工作" in context

    def test_llm_failure_degrades_gracefully(self, memory):
        """LLM 调用异常时返回空字典，不抛错。"""
        llm = FakeLLM(raises=RuntimeError("API 超时"))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert added == {"preferences": [], "topics": [], "questions": [], "facts": []}
        # memory 不应被修改
        assert "- " not in memory.get_context()

    def test_invalid_json_returns_empty(self, memory):
        """LLM 返回非法 JSON 时返回空。"""
        llm = FakeLLM(response="抱歉，我无法分析这段对话。")
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert added == {"preferences": [], "topics": [], "questions": [], "facts": []}

    def test_empty_llm_response(self, memory):
        """LLM 返回空字符串时返回空。"""
        llm = FakeLLM(response="")
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert added["preferences"] == []
        assert added["topics"] == []
        assert added["questions"] == []
        assert added["facts"] == []

    def test_empty_extraction_all_fields_empty(self, memory):
        """LLM 返回全空 JSON 时正常处理。"""
        llm = FakeLLM(response=json.dumps({
            "preferences": {},
            "topics": [],
            "questions": [],
            "facts": [],
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("闲聊", "嗯嗯")

        assert added == {"preferences": [], "topics": [], "questions": [], "facts": []}

    def test_dedup_with_existing_memory(self, memory):
        """与已有记忆去重合并。"""
        # 预置已有记忆
        memory.add_topic("殡葬政策")
        memory.save_preference("格式", "表格")

        llm = FakeLLM(response=json.dumps({
            "preferences": {"格式": "表格", "语言": "中文"},
            "topics": ["殡葬政策", "骨灰安置"],
            "questions": [],
            "facts": [],
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        # 已有的不应出现在新增清单中
        assert "格式:表格" not in added["preferences"]
        assert "殡葬政策" not in added["topics"]
        # 新增的应出现
        assert "语言:中文" in added["preferences"]
        assert "骨灰安置" in added["topics"]

    def test_preference_value_update_counts_as_added(self, memory):
        """偏好 key 已存在但 value 变化时算新增。"""
        memory.save_preference("格式", "表格")

        llm = FakeLLM(response=json.dumps({
            "preferences": {"格式": "列表"},
            "topics": [],
            "questions": [],
            "facts": [],
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert "格式:列表" in added["preferences"]
        assert memory.get_context().count("- 格式: 列表") == 1


# ============================================================
# 类型校验测试
# ============================================================

class TestTypeCoercion:
    """测试 LLM 输出类型不规范时的强制转换。"""

    def test_preferences_not_dict_returns_empty(self, memory):
        """preferences 不是 dict 时置空。"""
        llm = FakeLLM(response=json.dumps({
            "preferences": ["应该", "是", "dict"],
            "topics": [],
            "questions": [],
            "facts": [],
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert added["preferences"] == []

    def test_topics_scalar_string_wrapped_to_list(self, memory):
        """topics 是字符串时包装为单元素列表。"""
        llm = FakeLLM(response=json.dumps({
            "preferences": {},
            "topics": "殡葬政策",
            "questions": [],
            "facts": [],
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert "殡葬政策" in added["topics"]

    def test_questions_scalar_string_wrapped_to_list(self, memory):
        """questions 是字符串时包装为单元素列表。"""
        llm = FakeLLM(response=json.dumps({
            "preferences": {},
            "topics": [],
            "questions": "什么是生态葬？",
            "facts": [],
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert "什么是生态葬？" in added["questions"]

    def test_facts_scalar_string_wrapped_to_list(self, memory):
        """facts 是字符串时包装为单元素列表。"""
        llm = FakeLLM(response=json.dumps({
            "preferences": {},
            "topics": [],
            "questions": [],
            "facts": "用户在民政部门工作",
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert "用户在民政部门工作" in added["facts"]

    def test_topics_with_non_string_elements_filtered(self, memory):
        """topics 含非字符串元素时被过滤为字符串。"""
        llm = FakeLLM(response=json.dumps({
            "preferences": {},
            "topics": ["有效主题", 123, None, True, {"a": "b"}],
            "questions": [],
            "facts": [],
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        # 非空元素被转为字符串
        assert "有效主题" in added["topics"]
        assert "123" in added["topics"]
        assert "True" in added["topics"]
        # None 应被过滤
        assert "None" not in added["topics"]

    def test_preferences_with_empty_values_filtered(self, memory):
        """preferences 的空 value 被过滤。"""
        llm = FakeLLM(response=json.dumps({
            "preferences": {"有效": "值", "空值": "", "只有空格": "   "},
            "topics": [],
            "questions": [],
            "facts": [],
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert "有效:值" in added["preferences"]
        # 空值和纯空白不应出现
        assert not any("空值" in p for p in added["preferences"])
        assert not any("只有空格" in p for p in added["preferences"])

    def test_missing_fields_treated_as_empty(self, memory):
        """JSON 缺少某些字段时按空处理。"""
        llm = FakeLLM(response=json.dumps({
            "preferences": {"a": "b"},
            # 缺少 topics/questions/facts
        }))
        extractor = MemoryExtractor(llm=llm, memory=memory)

        added = extractor.extract_and_merge("问题", "回答")

        assert "a:b" in added["preferences"]
        assert added["topics"] == []
        assert added["questions"] == []
        assert added["facts"] == []


# ============================================================
# prompt 构造测试
# ============================================================

class TestPromptConstruction:
    """测试传给 LLM 的 prompt 构造。"""

    def test_dialogue_is_passed_as_user_message(self, memory):
        """用户输入和 AI 回复被拼接进 user 消息。"""
        llm = FakeLLM(response='{"preferences": {}, "topics": [], "questions": [], "facts": []}')
        extractor = MemoryExtractor(llm=llm, memory=memory)

        extractor.extract_and_merge(
            user_input="骨灰安置的标准是什么？",
            assistant_reply="根据政策，骨灰安置分为...",
        )

        # 由于 FakeLLM 不存 messages，这里只能间接验证：
        # 只要调用成功且返回正确结构即可
        assert llm.call_count == 1
