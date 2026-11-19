"""System adapters for Clock and IdGenerator ports."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from application.ports import Clock, IdGenerator


class UtcClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class Uuid4Generator(IdGenerator):
    def new_id(self) -> UUID:
        return uuid4()
