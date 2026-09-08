import shutil
from pathlib import Path
from typing import Iterator

import docker
from docker.errors import NotFound, APIError, DockerException

from .config import BOTS_DIR

_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            _client = docker.from_env()
        except DockerException as exc:
            raise RuntimeError(
                "Could not reach the Docker daemon. Is Docker installed and running, "
                "and does this process have permission to use it?"
            ) from exc
    return _client

DEFAULT_DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
CMD ["python", "main.py"]
"""


def bot_dir(bot_id: str) -> Path:
    d = BOTS_DIR / bot_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def folder_size_mb(path: Path) -> float:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total / (1024 * 1024)


def ensure_dockerfile(path: Path):
    dockerfile = path / "Dockerfile"
    if not dockerfile.exists():
        dockerfile.write_text(DEFAULT_DOCKERFILE)
    main_py = path / "main.py"
    if not main_py.exists() and not dockerfile.exists():
        pass  # client is responsible for creating main.py; deploy will fail clearly if missing


def build_image(bot_id: str) -> str:
    path = bot_dir(bot_id)
    ensure_dockerfile(path)
    tag = f"bot-{bot_id}:latest"
    _get_client().images.build(path=str(path), tag=tag, rm=True, forcerm=True)
    return tag


def run_container(
    bot_id: str,
    image_tag: str,
    discord_token: str,
    ram_mb: int,
    cpu_cores: float,
) -> str:
    stop_and_remove_container(bot_id)  # in case a stale one exists
    container = _get_client().containers.run(
        image_tag,
        name=f"bot-{bot_id}",
        detach=True,
        environment={"DISCORD_TOKEN": discord_token},
        mem_limit=f"{ram_mb}m",
        memswap_limit=f"{ram_mb}m",  # no swap beyond the RAM cap
        nano_cpus=int(cpu_cores * 1_000_000_000),
        network_mode="bridge",
        restart_policy={"Name": "no"},
        pids_limit=256,
        read_only=False,
    )
    return container.id


def stop_and_remove_container(bot_id: str):
    try:
        c = _get_client().containers.get(f"bot-{bot_id}")
        c.stop(timeout=5)
        c.remove(force=True)
    except NotFound:
        pass
    except APIError:
        pass


def container_status(bot_id: str) -> str:
    try:
        c = _get_client().containers.get(f"bot-{bot_id}")
        return c.status  # running, exited, ...
    except NotFound:
        return "stopped"


def stream_logs(bot_id: str) -> Iterator[bytes]:
    try:
        c = _get_client().containers.get(f"bot-{bot_id}")
    except NotFound:
        yield b"[no running container for this bot]\n"
        return
    for chunk in c.logs(stream=True, follow=True, tail=200):
        yield chunk


def remove_image(image_tag: str):
    try:
        _get_client().images.remove(image_tag, force=True)
    except (NotFound, APIError):
        pass


def delete_bot_files(bot_id: str):
    path = BOTS_DIR / bot_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
