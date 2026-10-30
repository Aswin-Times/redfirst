from logging.config import fileConfig

from alembic import context

from redfirst.db.models import Base
from redfirst.db.session import make_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url") or make_engine().url.render_as_string(False)
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests inject a ready engine via config.attributes; otherwise use REDFIRST_DATABASE_URL.
    engine = config.attributes.get("engine") or make_engine()
    sqlite = engine.dialect.name == "sqlite"
    with engine.connect() as connection:
        if sqlite:
            # SQLite batch migrations recreate tables (DROP TABLE + copy). With foreign keys
            # enforced, dropping a parent table that has child rows fails. This is Alembic's
            # documented recipe: disable enforcement for the migration, verify integrity
            # afterwards, and always restore it (the connection returns to the pool).
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        try:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
            if sqlite:
                connection.commit()
                violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(
                        f"migration left {len(violations)} foreign key violation(s): "
                        f"{[tuple(v) for v in violations[:5]]}")
        finally:
            if sqlite:
                connection.rollback()
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
