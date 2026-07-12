from logging.config import fileConfig

from alembic import context
import sqlalchemy as sa

from backend.models.database import Base, DATABASE_URL
import backend.models.comic  # noqa: F401 - 注册全部 ORM metadata


config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def compare_type(
    migration_context,
    inspected_column,
    metadata_column,
    inspected_type,
    metadata_type,
):
    """SQLite 会把 non-native Enum 反射成 VARCHAR；两者在本项目中视为同一物理类型。"""

    del migration_context, inspected_column, metadata_column
    if isinstance(metadata_type, sa.Enum) and isinstance(inspected_type, sa.String):
        return False
    return None


def run_migrations_offline() -> None:
    """离线模式只生成 SQL，不创建 Engine。"""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=compare_type,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """复用应用 Engine，保证 .env 和自定义 SQLite 路径行为一致。"""

    from backend.models.database import engine

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=compare_type,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
