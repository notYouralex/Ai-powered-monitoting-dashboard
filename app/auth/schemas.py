from pydantic import BaseModel, Field


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=1024)
    is_admin: bool = False


class UserSummary(BaseModel):
    username: str
    is_active: bool
    is_admin: bool
