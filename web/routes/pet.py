"""宠物管理 — 状态查询 + 交互操作。

GET  /api/pet/status    宠物状态
POST /api/pet/interact  喂食/玩耍/训练
POST /api/pet/style     切换人格
POST /api/pet/adopt     领养宠物
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["pet"])


def _get_pet():
    """获取当前宠物，没有则返回 None。"""
    from core.pet.storage import PetStorage
    return PetStorage().load()


def _pet_to_dict(pet) -> dict:
    """安全的 Pet → dict 转换，兼容所有属性名。"""
    return {
        "name": pet.name,
        "level": pet.level,
        "exp": pet.exp,
        "exp_needed": pet.exp_needed() if hasattr(pet, "exp_needed") else 100,
        "branch": getattr(pet, "branch", None),
        "style": getattr(pet, "branch", None) or "auto",  # branch 映射为 style
        "hunger": getattr(pet, "hunger", 60),
        "mood": getattr(pet, "mood", 80),
        "energy": getattr(pet, "energy", 75),
        "cleanliness": getattr(pet, "cleanliness", 80),
    }


@router.get("/pet/status")
async def pet_status():
    """获取宠物状态。"""
    pet = _get_pet()
    if pet is None:
        return {"found": False, "message": "尚未领养宠物，请先领养"}

    return {
        "found": True,
        **_pet_to_dict(pet),
        "message": "OK",
    }


class PetInteractBody(BaseModel):
    action: str  # "feed" | "play" | "train" | "sleep" | "wash"


@router.post("/pet/interact")
async def pet_interact(body: PetInteractBody):
    """宠物互动（喂食/玩耍/训练/睡觉/洗澡）。"""
    pet = _get_pet()
    if pet is None:
        raise HTTPException(status_code=404, detail="尚未领养宠物")

    try:
        from core.pet.interact import PetInteractor
        from core.pet.storage import PetStorage

        interactor = PetInteractor()
        if body.action == "feed":
            result = interactor.feed(pet)
        elif body.action == "play":
            result = interactor.play(pet)
        elif body.action == "train":
            result = interactor.train(pet)
        elif body.action == "sleep":
            result = interactor.sleep(pet)
        elif body.action == "wash":
            result = interactor.wash(pet)
        else:
            raise HTTPException(status_code=400, detail=f"未知操作: {body.action}")

        PetStorage().save(pet)

        return {
            "pet": _pet_to_dict(pet),
            "message": result.get("message", f"完成: {body.action}"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"互动失败: {e}")


class PetStyleBody(BaseModel):
    style: str  # "scholar" | "warrior" | "artisan" | "auto"


@router.post("/pet/style")
async def pet_style(body: PetStyleBody):
    """切换宠物人格风格。"""
    pet = _get_pet()
    if pet is None:
        raise HTTPException(status_code=404, detail="尚未领养宠物")

    valid_styles = {"scholar", "warrior", "artisan", "auto", "neutral"}
    if body.style not in valid_styles:
        raise HTTPException(status_code=400, detail=f"无效风格: {body.style}，可选: {', '.join(sorted(valid_styles))}")

    try:
        from core.pet.storage import PetStorage

        # branch 是 Pet 类上的属性
        style_value = None if body.style == "auto" else body.style
        pet.branch = style_value
        PetStorage().save(pet)

        return {
            "pet": _pet_to_dict(pet),
            "message": f"风格已切换为: {body.style}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"切换失败: {e}")


class PetAdoptBody(BaseModel):
    name: str


@router.post("/pet/adopt")
async def pet_adopt(body: PetAdoptBody):
    """领养宠物。"""
    try:
        from core.pet.pet import Pet
        from core.pet.storage import PetStorage

        existing = PetStorage().load()
        if existing:
            return {
                "pet": _pet_to_dict(existing),
                "message": f"你已经有宠物「{existing.name}」了",
            }

        pet = Pet(name=body.name)
        PetStorage().save(pet)

        # ASCII 艺术
        ascii_art = ""
        try:
            from core.pet.art import ArtLibrary
            lib = ArtLibrary()
            ascii_art = lib.get(branch=None, level=1)
        except Exception:
            pass

        return {
            "pet": _pet_to_dict(pet),
            "ascii_art": ascii_art,
            "message": f"领养成功！欢迎 {body.name}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"领养失败: {e}")
