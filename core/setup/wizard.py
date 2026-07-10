"""首次运行引导向导。"""
from __future__ import annotations

import getpass
import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from config import settings, PROJECT_ROOT

console = Console()


def run_wizard() -> bool:
    """运行首次配置引导。

    Returns:
        True 表示配置完成，False 表示用户跳过或中断。
    """
    console.print(Panel(
        "[bold cyan]IMA 知识库初始化引导[/bold cyan]\n"
        "接下来将引导你完成 5 步配置，每步均可跳过。",
        title="欢迎使用 IMA",
        border_style="cyan",
    ))

    # Step 1: 配置 LLM API Key
    _step_config_llm()

    # Step 2: 领养宠物
    _step_adopt_pet()

    # Step 3: 选择人格风格
    _step_choose_persona()

    # Step 4: 入库首批文档（可选）
    _step_ingest_docs()

    # Step 5: 生成 IMA.md
    _step_generate_memory()

    console.print("\n[bold green]配置完成！[/bold green] 输入 [cyan]ima[/cyan] 开始使用。")
    return True


def _step_config_llm() -> None:
    """Step 1: 配置 LLM API Key。"""
    console.print("\n[bold]Step 1/5: 配置 AI 模型[/bold]")
    console.print("[dim]IMA 使用 Agnes AI 提供问答能力。跳过则仅支持搜索功能。[/dim]")

    # 检查已有配置
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        existing_key = os.environ.get("AGNES_API_KEY", "")
        if existing_key and existing_key not in ("sk-xxx", "your-api-key", "YOUR_API_KEY", ""):
            overwrite = Prompt.ask(
                f"  已检测到 API Key ({existing_key[:8]}...), 是否重新配置?",
                choices=["y", "n"], default="n"
            )
            if overwrite == "n":
                console.print("  [green]跳过[/green]")
                return

    api_key = getpass.getpass("  请输入 Agnes API Key (sk-xxx, 直接回车跳过): ").strip()
    if not api_key:
        console.print("  [yellow]跳过 LLM 配置，将仅支持搜索功能[/yellow]")
        return

    # 验证格式
    if len(api_key) < 10:
        console.print("  [red]API Key 格式似乎不正确，已跳过[/red]")
        return

    # 写入或更新 .env
    _write_env({"AGNES_API_KEY": api_key})
    os.environ["AGNES_API_KEY"] = api_key
    console.print(f"  [green]已配置[/green] API Key: {api_key[:8]}...")


def _write_env(updates: dict) -> None:
    """写入或更新 .env 文件（保留已有内容）。"""
    env_path = PROJECT_ROOT / ".env"

    # 读取现有内容
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    # 更新或追加
    updated_keys = set()
    new_lines = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # 追加新键
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # 设置文件权限 600
    env_path.chmod(0o600)


def _step_adopt_pet() -> None:
    """Step 2: 领养宠物。"""
    console.print("\n[bold]Step 2/5: 领养知识库管家[/bold]")
    console.print("[dim]宠物是所有 AI 交互的入口，会随使用成长。[/dim]")

    from core.pet.storage import PetStorage
    pet_storage = PetStorage()
    existing_pet = pet_storage.load()

    if existing_pet:
        overwrite = Prompt.ask(
            f"  已有宠物 [{existing_pet.name}], 是否重新领养?",
            choices=["y", "n"], default="n"
        )
        if overwrite == "n":
            console.print(f"  [green]保留现有宠物[/green]: {existing_pet.name}")
            return

    name = Prompt.ask("  给你的管家起个名字", default="小林同学")
    if not name.strip():
        name = "小林同学"

    # 创建宠物
    from core.pet.pet import Pet
    pet = Pet(name=name.strip())
    pet_storage.save(pet)
    console.print(f"  [green]领养成功[/green]: {name.strip()}")


def _step_choose_persona() -> None:
    """Step 3: 选择人格风格。"""
    console.print("\n[bold]Step 3/5: 选择人格风格[/bold]")
    console.print("[dim]影响 AI 回复的语气和结构。[/dim]")

    personas = {
        "scholar": "学者·深度分析（详尽严谨）",
        "warrior": "战士·直接行动（简洁高效）",
        "artisan": "工匠·结构化（条理清晰）",
        "auto": "自动（根据问题智能选择）",
    }

    console.print("  可选风格:")
    for key, desc in personas.items():
        console.print(f"    [cyan]{key:8}[/cyan] {desc}")

    choice = Prompt.ask("  选择默认人格", choices=list(personas.keys()), default="scholar")

    # 写入 ProfileManager（适配实际接口）
    from core.memory.store import MemoryStore
    from core.memory.profile import ProfileManager
    memory = MemoryStore()
    pm = ProfileManager(memory)
    pm.update_style_preference(choice)

    console.print(f"  [green]已设置[/green]: {personas[choice]}")


def _step_ingest_docs() -> None:
    """Step 4: 入库首批文档（可选）。"""
    console.print("\n[bold]Step 4/5: 入库首批文档[/bold]")
    console.print("[dim]拖入文件路径或输入目录，直接回车跳过。[/dim]")

    path = Prompt.ask("  文档路径", default="")
    if not path.strip():
        console.print("  [yellow]跳过，可稍后用 ima ingest <路径> 入库[/yellow]")
        return

    from core.ingestion.parser import is_supported, SUPPORTED_EXTENSIONS
    target = Path(path.strip()).expanduser().resolve()

    if not target.exists():
        console.print(f"  [red]路径不存在: {target}[/red]")
        return

    files = []
    if target.is_file():
        files = [target]
    elif target.is_dir():
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(target.rglob(f"*{ext}"))
        files = sorted(set(files))

    if not files:
        console.print("  [yellow]未找到支持的文件[/yellow]")
        return

    console.print(f"  发现 {len(files)} 个文件，开始入库...")

    from core.storage import Storage
    from core.ingestion.parser import parse
    from core.ingestion.chunker import chunk_document
    storage = Storage()

    success = 0
    for f in files:
        try:
            if not is_supported(f):
                continue
            parsed = parse(f)
            if not parsed.text.strip():
                continue
            chunks = chunk_document(
                parsed,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
            record = storage.save_document(parsed, chunks, copy_file=True)
            success += 1
            console.print(f"    [green]✓[/green] {f.name} ({record.chunk_count} 块)")
        except Exception as e:
            console.print(f"    [red]✗[/red] {f.name}: {e}")

    console.print(f"  [green]入库完成[/green]: {success}/{len(files)} 成功")


def _step_generate_memory() -> None:
    """Step 5: 生成 IMA.md 项目记忆文件。"""
    console.print("\n[bold]Step 5/5: 生成项目记忆[/bold]")

    memory_path = PROJECT_ROOT / "IMA.md"

    # 收集配置摘要
    from core.pet.storage import PetStorage
    from core.memory.store import MemoryStore
    from core.memory.profile import ProfileManager

    pet_storage = PetStorage()
    pet = pet_storage.load()
    memory = MemoryStore()
    pm = ProfileManager(memory)
    profile = pm.get_profile()

    from core.storage import Storage
    storage = Storage()
    doc_count = len(storage.list_documents())

    content = f"""# IMA 知识库项目记忆

## 配置摘要

- **AI 模型**: {settings.llm_model if settings.has_llm() else "未配置（仅搜索模式）"}
- **宠物管家**: {pet.name if pet else "未领养"}
- **人格风格**: {profile.preferred_style or "scholar"}
- **文档数量**: {doc_count}

## 使用指南

- `ima` — 进入交互式 REPL
- `ima -p "问题"` — 单次问答
- `ima ingest <路径>` — 入库文档
- `ima search <关键词>` — 搜索
- `ima init` — 重新配置

## 项目结构

- `core/` — 核心模块（检索/记忆/人格/宠物/Agent）
- `core/cli/` — REPL 命令处理
- `core/agent/tools/` — Agent 工具系统
- `web/` — Web 后台
- `storage/` — 数据存储（不入 git）

---
*此文件由 ima init 自动生成，可手动编辑。*
"""

    memory_path.write_text(content, encoding="utf-8")
    console.print(f"  [green]已生成[/green] {memory_path.name}")
