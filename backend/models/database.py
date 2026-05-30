import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# 启动时读取 .env，允许用 DATABASE_URL 覆盖默认 SQLite 路径。
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/comaic.sqlite3")

# engine 是 SQLAlchemy 访问数据库的入口；future=True 使用 2.x 风格 API。
engine = create_engine(DATABASE_URL, future=True)

# SessionLocal 用来创建一次数据库会话；Repository 会基于 session 读写数据。
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类，SQLAlchemy 会从这里收集表结构。"""

    pass


def init_db() -> None:
    """根据当前 ORM 模型创建数据库表。"""

    # 先导入模型模块，确保表定义已经注册到 Base.metadata。
    import backend.models.comic  # noqa: F401

    Base.metadata.create_all(bind=engine)
