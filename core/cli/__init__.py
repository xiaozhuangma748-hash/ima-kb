"""core.cli 包：REPL CLI 模块。

拆分自原 repl.py（4487 行单文件），使用 Mixin 模式组织：

- ``constants``  模块级常量与全局变量
- ``completer``  命令补全与输入读取
- ``welcome``    启动面板渲染
- ``chat``       AI 对话 Mixin
- ``repl``       REPL 主类（瘦壳，聚合所有 Mixin）
- ``main``       入口函数

命令 Mixin（core.cli.commands 子包）：
- ``docs``       文档管理（search/ingest/list/show/tag/...）
- ``analyze``    分析（report/read/compare）
- ``agent``      Agent 模式与智能路由
- ``sync``       同步与维护（sync/health/dedup/draw/daily/pic）
- ``session``    会话管理（save/load/list/export/delete）
- ``memory``     记忆管理与主题切换
- ``graph``      知识图谱
- ``pet``        虚拟宠物
- ``pipe``       管道链式调用
"""
