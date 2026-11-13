from alembic import context

from models.database import get_engine

config = context.config


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection") or get_engine()
    with connectable.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # SQLite rebuilds tables during migrations. With foreign keys on, dropping a parent table
            # would fail or cascade. They are switched off here and checked again after the run.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            # End SQLAlchemy's implicit transaction here. Otherwise Alembic sees one already open, does not
            # commit its own changes, and they are rolled back when the connection closes.
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=None,
            render_as_batch=sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(
                    f"Foreign key check failed after migration: {len(violations)} row(s) reference a missing parent. "
                    "The migration was not applied in a consistent state; restore from the backup."
                )


run_migrations_online()
