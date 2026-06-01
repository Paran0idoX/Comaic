from datetime import datetime, timezone

from sqlalchemy.types import String, TypeDecorator


def utc_now() -> datetime:
    """返回带 UTC 时区信息的当前时间，替代已弃用的 datetime.utcnow()。"""

    return datetime.now(timezone.utc)


class AwareUTCDateTime(TypeDecorator[datetime]):
    """把 aware UTC datetime 以 ISO8601 字符串存入 SQLite。

    SQLite 没有真正的 timezone-aware datetime 类型，SQLAlchemy 的
    DateTime(timezone=True) 在 SQLite 下也会丢掉 offset。这里显式存储
    `2026-06-01T06:34:31.123456+00:00` 这种字符串，保证数据库和 API
    都能保留 UTC 时区信息。
    """

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> str | None:
        """写库前统一转成 UTC ISO8601；禁止写入无时区时间。"""

        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime value must include timezone info.")
        return value.astimezone(timezone.utc).isoformat()

    def process_result_value(self, value: str | None, dialect) -> datetime | None:
        """读库后还原为带 UTC 时区的 datetime。"""

        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("stored datetime value must include timezone info.")
        return parsed.astimezone(timezone.utc)
