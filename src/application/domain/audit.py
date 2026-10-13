import uuid
from datetime import datetime
from typing import Any


class AuditLog:
    def __init__(
        self,
        *,
        id: uuid.UUID,
        entity_type: str | None,
        entity_id: uuid.UUID | None,
        action: str | None,
        payload: dict[str, Any] | None,
        created_at: datetime,
    ):
        self.id = id
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.action = action
        self.payload = payload
        self.created_at = created_at

    @classmethod
    def record(
        cls, entity_type: str, entity_id: uuid.UUID, action: str, payload: dict[str, Any], now: datetime
    ) -> "AuditLog":
        return cls(
            id=uuid.uuid4(),
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            payload=payload,
            created_at=now,
        )
