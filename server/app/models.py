import uuid
import datetime as dt

from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from .database import Base


def gen_id():
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    username = Column(String, unique=True, nullable=False)

    # Only a bcrypt hash of the login token is ever stored. The plaintext
    # token is shown to the admin exactly once, at creation/regeneration time.
    token_hash = Column(String, nullable=False)

    ram_mb = Column(Integer, default=256)
    cpu_cores = Column(Float, default=0.5)
    storage_mb = Column(Integer, default=500)
    max_bots = Column(Integer, default=1)

    created_at = Column(DateTime, default=dt.datetime.utcnow)

    bots = relationship("Bot", back_populates="owner", cascade="all, delete-orphan")


class Bot(Base):
    __tablename__ = "bots"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)

    # Discord bot token, encrypted at rest with Fernet. Decrypted only
    # in-memory, right before being injected into the container as an
    # environment variable at deploy time.
    discord_token_enc = Column(String, nullable=True)

    image_tag = Column(String, nullable=True)
    container_id = Column(String, nullable=True)
    status = Column(String, default="stopped")  # stopped | building | running | error

    created_at = Column(DateTime, default=dt.datetime.utcnow)

    owner = relationship("User", back_populates="bots")
