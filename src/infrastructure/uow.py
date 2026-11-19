"""SQLAlchemy UnitOfWork adapter."""

from sqlalchemy.orm import Session

from application.ports import UnitOfWork


class SqlAlchemyUnitOfWork(UnitOfWork):
    """Commits or rolls back a SQLAlchemy Session around write operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
