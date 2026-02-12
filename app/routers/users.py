from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_user_registry, get_current_user
from app.models.schemas import UserInfo, UserCreateRequest
from app.db.repositories import UserRepository

router = APIRouter()


@router.get("", response_model=list[UserInfo])
async def list_users(
    user_registry: UserRepository = Depends(get_user_registry),
):
    return [UserInfo(**u) for u in await user_registry.list_all()]


@router.post("", response_model=UserInfo, status_code=201)
async def create_user(
    request: UserCreateRequest,
    user_registry: UserRepository = Depends(get_user_registry),
):
    if await user_registry.exists(request.user_id):
        raise HTTPException(status_code=409, detail=f"User '{request.user_id}' already exists")
    user = await user_registry.add(request.user_id, request.display_name)
    return UserInfo(**user)


@router.get("/current", response_model=UserInfo)
async def get_current_user_info(
    current_user: str = Depends(get_current_user),
    user_registry: UserRepository = Depends(get_user_registry),
):
    user = await user_registry.get(current_user)
    if not user:
        # Auto-create user if they don't exist yet
        user = await user_registry.add(current_user, current_user.capitalize())
    return UserInfo(**user)
