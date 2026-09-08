from typing import Optional
from pydantic import BaseModel


class AdminLoginIn(BaseModel):
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreateIn(BaseModel):
    username: str
    ram_mb: int = 256
    cpu_cores: float = 0.5
    storage_mb: int = 500
    max_bots: int = 1


class UserUpdateIn(BaseModel):
    ram_mb: Optional[int] = None
    cpu_cores: Optional[float] = None
    storage_mb: Optional[int] = None
    max_bots: Optional[int] = None


class UserOut(BaseModel):
    id: str
    username: str
    ram_mb: int
    cpu_cores: float
    storage_mb: int
    max_bots: int
    bot_count: int


class NewLoginTokenOut(BaseModel):
    username: str
    login_token: str  # shown once, never retrievable again


class ClientLoginIn(BaseModel):
    token: str


class BotCreateIn(BaseModel):
    name: str


class BotOut(BaseModel):
    id: str
    name: str
    status: str
    has_discord_token: bool


class DiscordTokenIn(BaseModel):
    discord_token: str


class FileWriteIn(BaseModel):
    content: str
