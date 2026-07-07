"""虚拟宠物系统。"""
from core.pet.pet import Pet, BranchType
from core.pet.storage import PetStorage
from core.pet.art import ArtLibrary
from core.pet.interact import PetInteractor, InteractError
from core.pet.tasks import DailyTaskManager, TASK_POOL
from core.pet.shop import Shop, ShopError, ITEMS

__all__ = [
    "Pet", "BranchType", "PetStorage", "ArtLibrary",
    "PetInteractor", "InteractError",
    "DailyTaskManager", "TASK_POOL",
    "Shop", "ShopError", "ITEMS",
]
