"""Shared type aliases."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aredis

    # redis.asyncio.Redis is not subscriptable in this version; alias bare.
    RedisClient = aredis.Redis
else:
    # At runtime the class is not subscriptable in all redis versions, so we
    # alias to the bare class to keep isinstance/annotation usage working.
    import redis.asyncio as aredis

    RedisClient = aredis.Redis
