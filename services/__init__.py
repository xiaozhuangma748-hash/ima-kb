"""服务编排层。

CLI (run.py / core.cli) 和 Web (web/routes/) 共用的业务编排服务，
消除重复的组件组装代码。

- QAService       问答编排（PetAdministrator + 检索 + 重排 + 记忆 + LLM）
- IngestService   文档入库（解析 + 分块 + 去重 + 标签 + 保存）
"""
