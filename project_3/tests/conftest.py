import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self._kv: Dict[str, str] = {}
        self._hash: Dict[str, Dict[str, str]] = {}
        self._expires: Dict[str, int] = {}

    def get(self, key: str):
        return self._kv.get(key)

    def set(self, key: str, value: str):
        self._kv[key] = value
        return True

    def delete(self, key: str):
        self._kv.pop(key, None)
        self._hash.pop(key, None)
        self._expires.pop(key, None)
        return 1

    def hgetall(self, key: str):
        return dict(self._hash.get(key, {}))

    def hset(self, key: str, mapping: Dict[str, str]):
        self._hash[key] = dict(mapping)
        return len(mapping)

    def expire(self, key: str, seconds: int):
        self._expires[key] = seconds
        return True

    def flushall(self):
        self._kv.clear()
        self._hash.clear()
        self._expires.clear()


@pytest.fixture(scope="session", autouse=True)
def _test_env(tmp_path_factory):
    """
    Ensure env vars are set before importing the app module.
    We use a file-based SQLite DB to keep data across connections.
    """
    db_path = tmp_path_factory.mktemp("db") / "test.sqlite3"
    os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    os.environ.setdefault("REDIS_URL", "redis://fake/0")
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
    os.environ.setdefault("INACTIVE_DELETE_DAYS", "30")

    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


@pytest.fixture(scope="session")
def app_module(_test_env):
    import importlib

    mod = importlib.import_module("main")
    return mod


@pytest.fixture()
def fake_redis(app_module, mocker):
    r = FakeRedis()
    mocker.patch.object(app_module, "redis_client", r)
    return r


@pytest.fixture()
def db(app_module, fake_redis):
    app_module.Base.metadata.create_all(bind=app_module.engine)

    session = app_module.SessionLocal()
    try:
        session.query(app_module.ExpiredLinkHistory).delete()
        session.query(app_module.Link).delete()
        session.query(app_module.Project).delete()
        session.query(app_module.User).delete()
        session.commit()
        yield session
    finally:
        session.close()


@pytest.fixture()
def now_utc():
    return datetime.now(timezone.utc)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

