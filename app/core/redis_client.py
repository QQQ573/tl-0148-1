import json
from typing import Optional, Any
from datetime import timedelta
import redis.asyncio as redis

from app.core.config import settings


class RedisClient:
    _client: Optional[redis.Redis] = None

    @classmethod
    async def get_client(cls) -> redis.Redis:
        if cls._client is None:
            cls._client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return cls._client

    @classmethod
    async def close(cls):
        if cls._client:
            await cls._client.close()
            cls._client = None

    @classmethod
    async def get(cls, key: str) -> Optional[Any]:
        client = await cls.get_client()
        data = await client.get(key)
        if data:
            try:
                return json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return data
        return None

    @classmethod
    async def set(cls, key: str, value: Any, ex: Optional[timedelta] = None) -> None:
        client = await cls.get_client()
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        elif not isinstance(value, str):
            value = str(value)
        await client.set(key, value, ex=ex)

    @classmethod
    async def delete(cls, key: str) -> None:
        client = await cls.get_client()
        await client.delete(key)

    @classmethod
    async def exists(cls, key: str) -> bool:
        client = await cls.get_client()
        return await client.exists(key) > 0

    @classmethod
    async def setnx(cls, key: str, value: Any, ex: Optional[timedelta] = None) -> bool:
        client = await cls.get_client()
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        elif not isinstance(value, str):
            value = str(value)
        result = await client.set(key, value, nx=True, ex=ex)
        return result is not None

    @classmethod
    async def acquire_lock(cls, lock_key: str, timeout: int = 30) -> bool:
        return await cls.setnx(lock_key, "locked", ex=timedelta(seconds=timeout))

    @classmethod
    async def release_lock(cls, lock_key: str) -> None:
        await cls.delete(lock_key)


def get_student_month_lock_key(student_id: int, year: int, month: int) -> str:
    return f"lock:student:{student_id}:booking:{year}-{month}"


def get_booking_cache_key(booking_id: int) -> str:
    return f"cache:booking:{booking_id}"


def get_class_cache_key(class_id: int) -> str:
    return f"cache:class:{class_id}"
