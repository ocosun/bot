import secrets as _secrets
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from .config import ADMIN_PASSWORD, SERVER_TOTAL_RAM_MB, SERVER_TOTAL_CPU_CORES, SERVER_TOTAL_STORAGE_MB
from .database import Base, engine, get_db
from . import models, schemas, crypto, auth, docker_manager

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Bot Hosting Platform")


# ---------------------------------------------------------------- admin auth

@app.post("/admin/login", response_model=schemas.TokenOut)
def admin_login(body: schemas.AdminLoginIn):
    # Plain constant-time-ish compare is fine here: single fixed secret,
    # not a per-user lookup.
    if not _secrets.compare_digest(body.password, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Wrong admin password")
    token = auth.create_session_token(subject="admin", role="admin")
    return schemas.TokenOut(access_token=token)


# -------------------------------------------------------------- admin: users

@app.post("/admin/users", response_model=schemas.NewLoginTokenOut)
def create_user(body: schemas.UserCreateIn, db: Session = Depends(get_db), _=Depends(auth.require_admin)):
    if db.query(models.User).filter_by(username=body.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    login_token = crypto.new_login_token()
    user = models.User(
        username=body.username,
        token_hash=crypto.hash_login_token(login_token),
        ram_mb=body.ram_mb,
        cpu_cores=body.cpu_cores,
        storage_mb=body.storage_mb,
        max_bots=body.max_bots,
    )
    db.add(user)
    db.commit()
    return schemas.NewLoginTokenOut(username=user.username, login_token=login_token)


@app.get("/admin/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _=Depends(auth.require_admin)):
    out = []
    for u in db.query(models.User).all():
        out.append(schemas.UserOut(
            id=u.id, username=u.username, ram_mb=u.ram_mb, cpu_cores=u.cpu_cores,
            storage_mb=u.storage_mb, max_bots=u.max_bots, bot_count=len(u.bots),
        ))
    return out


@app.patch("/admin/users/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: str, body: schemas.UserUpdateIn, db: Session = Depends(get_db), _=Depends(auth.require_admin)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for field in ("ram_mb", "cpu_cores", "storage_mb", "max_bots"):
        val = getattr(body, field)
        if val is not None:
            setattr(user, field, val)
    db.commit()
    return schemas.UserOut(
        id=user.id, username=user.username, ram_mb=user.ram_mb, cpu_cores=user.cpu_cores,
        storage_mb=user.storage_mb, max_bots=user.max_bots, bot_count=len(user.bots),
    )


@app.post("/admin/users/{user_id}/regenerate-token", response_model=schemas.NewLoginTokenOut)
def regenerate_token(user_id: str, db: Session = Depends(get_db), _=Depends(auth.require_admin)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    login_token = crypto.new_login_token()
    user.token_hash = crypto.hash_login_token(login_token)
    db.commit()
    return schemas.NewLoginTokenOut(username=user.username, login_token=login_token)


@app.delete("/admin/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db), _=Depends(auth.require_admin)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for bot in user.bots:
        docker_manager.stop_and_remove_container(bot.id)
        if bot.image_tag:
            docker_manager.remove_image(bot.image_tag)
        docker_manager.delete_bot_files(bot.id)
    db.delete(user)
    db.commit()
    return {"ok": True}


@app.get("/admin/stats")
def admin_stats(db: Session = Depends(get_db), _=Depends(auth.require_admin)):
    users = db.query(models.User).all()
    return {
        "server_capacity": {
            "ram_mb": SERVER_TOTAL_RAM_MB,
            "cpu_cores": SERVER_TOTAL_CPU_CORES,
            "storage_mb": SERVER_TOTAL_STORAGE_MB,
        },
        "allocated": {
            "ram_mb": sum(u.ram_mb for u in users),
            "cpu_cores": sum(u.cpu_cores for u in users),
            "storage_mb": sum(u.storage_mb for u in users),
        },
        "user_count": len(users),
        "bot_count": sum(len(u.bots) for u in users),
    }


# --------------------------------------------------------------- client auth

@app.post("/auth/login", response_model=schemas.TokenOut)
def client_login(body: schemas.ClientLoginIn, db: Session = Depends(get_db)):
    for user in db.query(models.User).all():
        if crypto.verify_login_token(body.token, user.token_hash):
            token = auth.create_session_token(subject=user.id, role="client")
            return schemas.TokenOut(access_token=token)
    raise HTTPException(status_code=401, detail="Invalid login token")


@app.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(auth.require_client)):
    return schemas.UserOut(
        id=user.id, username=user.username, ram_mb=user.ram_mb, cpu_cores=user.cpu_cores,
        storage_mb=user.storage_mb, max_bots=user.max_bots, bot_count=len(user.bots),
    )


# --------------------------------------------------------------- client bots

@app.get("/bots", response_model=list[schemas.BotOut])
def list_bots(db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    return [
        schemas.BotOut(id=b.id, name=b.name, status=b.status, has_discord_token=bool(b.discord_token_enc))
        for b in user.bots
    ]


@app.post("/bots", response_model=schemas.BotOut)
def create_bot(body: schemas.BotCreateIn, db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    if len(user.bots) >= user.max_bots:
        raise HTTPException(status_code=403, detail=f"Bot limit reached ({user.max_bots})")
    bot = models.Bot(user_id=user.id, name=body.name)
    db.add(bot)
    db.commit()
    path = docker_manager.bot_dir(bot.id)
    (path / "main.py").write_text(
        "import os\n\n"
        "DISCORD_TOKEN = os.environ['DISCORD_TOKEN']\n\n"
        "# Write your bot here.\n"
    )
    (path / "requirements.txt").write_text("discord.py\n")
    return schemas.BotOut(id=bot.id, name=bot.name, status=bot.status, has_discord_token=False)


def _get_owned_bot(db: Session, user: models.User, bot_id: str) -> models.Bot:
    bot = db.get(models.Bot, bot_id)
    if not bot or bot.user_id != user.id:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


@app.delete("/bots/{bot_id}")
def delete_bot(bot_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    bot = _get_owned_bot(db, user, bot_id)
    docker_manager.stop_and_remove_container(bot.id)
    if bot.image_tag:
        docker_manager.remove_image(bot.image_tag)
    docker_manager.delete_bot_files(bot.id)
    db.delete(bot)
    db.commit()
    return {"ok": True}


@app.post("/bots/{bot_id}/discord-token")
def set_discord_token(bot_id: str, body: schemas.DiscordTokenIn, db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    bot = _get_owned_bot(db, user, bot_id)
    bot.discord_token_enc = crypto.encrypt_secret(body.discord_token)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------- client files

def _safe_path(bot_id: str, rel_path: str) -> Path:
    root = docker_manager.bot_dir(bot_id).resolve()
    target = (root / rel_path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="Invalid path")
    return target


@app.get("/bots/{bot_id}/files")
def list_files(bot_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    bot = _get_owned_bot(db, user, bot_id)
    root = docker_manager.bot_dir(bot.id)
    files = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            files.append(str(f.relative_to(root)))
    return {"files": files}


@app.get("/bots/{bot_id}/files/{rel_path:path}")
def read_file(bot_id: str, rel_path: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    bot = _get_owned_bot(db, user, bot_id)
    target = _safe_path(bot.id, rel_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return {"path": rel_path, "content": target.read_text(errors="replace")}


@app.put("/bots/{bot_id}/files/{rel_path:path}")
def write_file(bot_id: str, rel_path: str, body: schemas.FileWriteIn, db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    bot = _get_owned_bot(db, user, bot_id)
    target = _safe_path(bot.id, rel_path)

    projected_size = docker_manager.folder_size_mb(docker_manager.bot_dir(bot.id))
    if target.exists():
        projected_size -= target.stat().st_size / (1024 * 1024)
    projected_size += len(body.content.encode()) / (1024 * 1024)
    if projected_size > user.storage_mb:
        raise HTTPException(status_code=403, detail=f"Storage quota exceeded ({user.storage_mb} MB)")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content)
    return {"ok": True}


@app.delete("/bots/{bot_id}/files/{rel_path:path}")
def delete_file(bot_id: str, rel_path: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    bot = _get_owned_bot(db, user, bot_id)
    target = _safe_path(bot.id, rel_path)
    if target.exists():
        target.unlink()
    return {"ok": True}


# ----------------------------------------------------------- deploy/stop/logs

@app.post("/bots/{bot_id}/deploy")
def deploy_bot(bot_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    bot = _get_owned_bot(db, user, bot_id)
    if not bot.discord_token_enc:
        raise HTTPException(status_code=400, detail="Set a Discord bot token first")

    bot.status = "building"
    db.commit()
    try:
        image_tag = docker_manager.build_image(bot.id)
        discord_token = crypto.decrypt_secret(bot.discord_token_enc)
        container_id = docker_manager.run_container(
            bot.id, image_tag, discord_token, user.ram_mb, user.cpu_cores,
        )
        bot.image_tag = image_tag
        bot.container_id = container_id
        bot.status = "running"
        db.commit()
    except Exception as exc:
        bot.status = "error"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Deploy failed: {exc}")
    return {"ok": True, "status": bot.status}


@app.post("/bots/{bot_id}/stop")
def stop_bot(bot_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_client)):
    bot = _get_owned_bot(db, user, bot_id)
    docker_manager.stop_and_remove_container(bot.id)
    bot.status = "stopped"
    db.commit()
    return {"ok": True}


@app.websocket("/bots/{bot_id}/logs")
async def bot_logs(websocket: WebSocket, bot_id: str, token: str = Query(...)):
    from .database import SessionLocal

    payload = auth.decode_ws_token(token, expected_role="client")
    db = SessionLocal()
    try:
        bot = db.get(models.Bot, bot_id)
        if not bot or bot.user_id != payload.get("sub"):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        try:
            for chunk in docker_manager.stream_logs(bot.id):
                await websocket.send_text(chunk.decode(errors="replace"))
        except WebSocketDisconnect:
            pass
    finally:
        db.close()
