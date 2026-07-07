"""用户偏好：主题/地区/格式/风格。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import jieba

from core.memory.store import MemoryStore


# 已知地区关键词（用于从查询中提取）
# 注意："杭州" 必须放在 "杭州市" 之后，这样查询 "杭州市骨灰安置" 会先匹配到 "杭州市"，
# 而查询 "杭州骨灰安置"（不带"市"）才会匹配到 "杭州"。
_KNOWN_REGIONS = [
    "杭州市", "杭州市区", "拱墅区", "西湖区", "上城区", "滨江区",
    "余杭区", "萧山区", "富阳区", "临安区", "临平区", "钱塘区",
    "浙江省", "杭州",  # 兼容不带"市"的查询
    "北京", "上海", "广州", "深圳",
]

# 停用词：这些词不应当作用户主题（多为对话开场白或疑问词）
# 避免出现 "帮我"、"你是"、"请问" 等无意义主题
_STOP_WORDS = {
    # 对话开场/人称代词
    "帮我", "帮我们", "帮", "请帮", "请你", "你帮", "帮我看看", "帮我查",
    "你是", "你是谁", "你", "你们", "您的", "您", "我", "我们", "我的", "我是",
    "他", "她", "它", "他们", "她们", "它们",
    # 疑问/请求词
    "请问", "请", "请问一下", "麻烦", "麻烦你", "能不能", "可以", "可以吗",
    "什么", "怎么", "怎样", "怎么样", "为什么", "为何", "哪", "哪个", "哪些",
    "哪里", "哪儿", "是否", "是不是", "有没有", "有没有的", "如何", "啥",
    "多少", "几个", "几种", "多久", "什么时候",
    # 助词/语气词
    "的", "了", "是", "在", "和", "与", "及", "或", "等", "之", "其", "其它",
    "啊", "呀", "吧", "嘛", "哦", "呢", "哈", "嘿", "嗯", "诶",
    "地", "得", "着", "过", "们", "给", "把", "被", "让", "使", "对", "向",
    # 量词/副词
    "个", "些", "点", "下", "上", "里", "中", "内", "外", "前", "后",
    "一", "一个", "一种", "这个", "那个", "这些", "那些", "这样", "那样",
    "一下", "一会儿", "一阵", "一些", "一点",
    "就是", "还有", "也是", "或者", "但是", "不过", "然后", "所以", "因为",
    "已经", "正在", "将要", "将要", "马上", "现在", "今天", "明天", "昨天",
    # 动词（泛义）
    "有", "做", "看", "说", "想", "要", "会", "能", "可能", "需要", "应该",
    "知道", "告诉", "给", "找", "用", "来", "去", "到", "回", "出", "进",
    "看看", "查", "查查", "找找", "试试", "说说", "想想",
    "是谁", "是什么", "有哪些", "是怎样的",
    # 介词/连词
    "关于", "对于", "根据", "按照", "通过", "基于", "鉴于", "至于",
    "如果", "虽然", "尽管", "即使", "除非", "只要", "只有",
    # 标点/符号
    " ", "　", "，", "。", "？", "！", "、", "：", "；", "“", "”", "‘", "’",
    "（", "）", "《", "》", "【", "】", "\n", "\t", "\r",
}

# 允许的格式偏好值
VALID_FORMATS = {"", "table", "list", "prose", "auto"}
# 允许的风格偏好值
VALID_STYLES = {"auto", "scholar", "warrior", "artisan"}

# 人称代词首字：以这些字开头的词通常是代词+动词组合（如"我查"、"你找"），不是主题
_PRONOUN_FIRST_CHARS = set("我你他她它您")


@dataclass
class Profile:
    """用户偏好。"""
    preferred_format: str = ""           # table / list / prose / auto
    preferred_style: str = "auto"        # auto / scholar / warrior / artisan
    focus_topics: List[str] = field(default_factory=list)
    focus_regions: List[str] = field(default_factory=list)
    interaction_count: int = 0
    last_active: str = ""


def _extract_topic(query: str) -> str:
    """从查询中提取主题：用 jieba 分词，过滤停用词和单字词后取前 2 个有意义的词拼接。

    过滤规则：
        1. 过滤空白词
        2. 过滤停用词（_STOP_WORDS）：对话开场白、人称代词、疑问词、助词等
        3. 过滤单字词：中文主题通常是 2 字及以上名词性短语，单字词多为助词/量词
        4. 过滤以人称代词开头的词：如"我查"、"你找"等代词+动词组合

    示例：
        "骨灰安置政策" -> ["骨灰", "安置", "政策"] -> "骨灰安置"
        "杭州市骨灰安置" -> ["杭州市", "骨灰", "安置"] -> "杭州市骨灰"
        "帮我查一下骨灰安置" -> 过滤掉"帮"/"我查"/"一下" -> ["骨灰", "安置"] -> "骨灰安置"
        "你是谁" -> 全是停用词或单字 -> ""
    """
    query = query.strip()
    if not query:
        return ""
    words = [
        w for w in jieba.cut(query)
        if w.strip()
        and w not in _STOP_WORDS
        and len(w) >= 2
        and w[0] not in _PRONOUN_FIRST_CHARS
    ]
    return "".join(words[:2]) if words else ""


class ProfileManager:
    """用户偏好管理。"""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def get_profile(self) -> Profile:
        """读取当前偏好。"""
        data = self.store.get_data()
        profile_data = data.get("profile", {})
        return Profile(
            preferred_format=profile_data.get("preferred_format", ""),
            preferred_style=profile_data.get("preferred_style", "auto"),
            focus_topics=profile_data.get("focus_topics", []),
            focus_regions=profile_data.get("focus_regions", []),
            interaction_count=profile_data.get("interaction_count", 0),
            last_active=profile_data.get("last_active", ""),
        )

    def update_format_preference(self, format: str) -> None:
        """更新格式偏好。

        Args:
            format: 允许的值见 VALID_FORMATS（"" / "table" / "list" / "prose" / "auto"）

        Raises:
            ValueError: format 不在 VALID_FORMATS 中
        """
        if format not in VALID_FORMATS:
            raise ValueError(
                f"无效的格式偏好 '{format}'，允许值: {sorted(VALID_FORMATS - {''})} 或留空"
            )
        self.store.update("profile", "preferred_format", format)
        self.store.save()

    def update_style_preference(self, style: str) -> None:
        """更新风格偏好。

        Args:
            style: 允许的值见 VALID_STYLES（"auto" / "scholar" / "warrior" / "artisan"）

        Raises:
            ValueError: style 不在 VALID_STYLES 中
        """
        if style not in VALID_STYLES:
            raise ValueError(
                f"无效的风格偏好 '{style}'，允许值: {sorted(VALID_STYLES)}"
            )
        self.store.update("profile", "preferred_style", style)
        self.store.save()

    def add_topic(self, topic: str) -> bool:
        """手动添加一个主题。

        Args:
            topic: 主题字符串（非空）

        Returns:
            True 表示新增成功，False 表示已存在（包含关系去重）

        Raises:
            ValueError: topic 为空或纯空白
        """
        topic = topic.strip()
        if not topic:
            raise ValueError("主题不能为空")
        data = self.store.get_data()
        profile = data.setdefault("profile", {})
        if not isinstance(profile, dict):
            profile = {}
            data["profile"] = profile
        topics = profile.setdefault("focus_topics", [])
        # 包含关系去重
        if any(topic in t or t in topic for t in topics):
            return False
        topics.append(topic)
        if len(topics) > 10:
            topics.pop(0)
        self.store.save()
        return True

    def remove_topic(self, topic: str) -> bool:
        """删除一个主题（精确匹配）。

        Args:
            topic: 要删除的主题字符串

        Returns:
            True 表示删除成功，False 表示未找到
        """
        topic = topic.strip()
        if not topic:
            return False
        data = self.store.get_data()
        profile = data.get("profile", {})
        if not isinstance(profile, dict):
            return False
        topics = profile.get("focus_topics", [])
        if topic not in topics:
            return False
        topics.remove(topic)
        self.store.save()
        return True

    def clear_topics(self) -> int:
        """清空所有主题。

        Returns:
            被清除的主题数量
        """
        data = self.store.get_data()
        profile = data.get("profile", {})
        if not isinstance(profile, dict):
            return 0
        topics = profile.get("focus_topics", [])
        count = len(topics)
        profile["focus_topics"] = []
        self.store.save()
        return count

    # ---- 地区管理（与主题对称） ----

    def add_region(self, region: str) -> bool:
        """手动添加一个关注地区。

        Args:
            region: 地区字符串（非空）

        Returns:
            True 表示新增成功，False 表示已存在

        Raises:
            ValueError: region 为空或纯空白
        """
        region = region.strip()
        if not region:
            raise ValueError("地区不能为空")
        data = self.store.get_data()
        profile = data.setdefault("profile", {})
        if not isinstance(profile, dict):
            profile = {}
            data["profile"] = profile
        regions = profile.setdefault("focus_regions", [])
        if region in regions:
            return False
        regions.append(region)
        if len(regions) > 10:
            regions.pop(0)
        self.store.save()
        return True

    def remove_region(self, region: str) -> bool:
        """删除一个关注地区（精确匹配）。

        Args:
            region: 要删除的地区字符串

        Returns:
            True 表示删除成功，False 表示未找到
        """
        region = region.strip()
        if not region:
            return False
        data = self.store.get_data()
        profile = data.get("profile", {})
        if not isinstance(profile, dict):
            return False
        regions = profile.get("focus_regions", [])
        if region not in regions:
            return False
        regions.remove(region)
        self.store.save()
        return True

    def clear_regions(self) -> int:
        """清空所有关注地区。

        Returns:
            被清除的地区数量
        """
        data = self.store.get_data()
        profile = data.get("profile", {})
        if not isinstance(profile, dict):
            return 0
        regions = profile.get("focus_regions", [])
        count = len(regions)
        profile["focus_regions"] = []
        self.store.save()
        return count

    def update_from_query(self, query: str, answer: str) -> None:
        """从查询中提取主题和地区，更新偏好。"""
        data = self.store.get_data()
        profile = data.setdefault("profile", {})
        if not isinstance(profile, dict):
            profile = {}
            data["profile"] = profile

        # 提取主题（jieba 分词取前 2 个词拼接）
        topic = _extract_topic(query)
        if topic:
            topics = profile.setdefault("focus_topics", [])
            # 去重：包含关系不重复添加
            if not any(topic in t or t in topic for t in topics):
                topics.append(topic)
                # 最多保留 10 个
                if len(topics) > 10:
                    topics.pop(0)

        # 提取地区
        regions = profile.setdefault("focus_regions", [])
        for region in _KNOWN_REGIONS:
            if region in query and region not in regions:
                regions.append(region)
                if len(regions) > 10:
                    regions.pop(0)

        # 更新计数和时间
        profile["interaction_count"] = profile.get("interaction_count", 0) + 1
        profile["last_active"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        self.store.save()
