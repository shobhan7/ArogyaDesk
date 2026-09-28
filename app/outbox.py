import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NotificationLog, OutboxEvent


class EventPublisher:
    def publish(self, key: str, payload: str) -> None:
        raise NotImplementedError


class RecordingPublisher(EventPublisher):
    """Test double that keeps messages in memory."""

    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    def publish(self, key: str, payload: str) -> None:
        self.messages.append((key, payload))


class KafkaPublisher(EventPublisher):
    def __init__(self, bootstrap: str, topic: str):
        from kafka import KafkaProducer

        self.topic = topic
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap.split(","),
            acks="all",
            retries=3,
        )

    def publish(self, key: str, payload: str) -> None:
        future = self.producer.send(
            self.topic, key=key.encode(), value=payload.encode()
        )
        future.get(timeout=10)


def enqueue(
    db: Session,
    aggregate_type: str,
    aggregate_id: int,
    event_type: str,
    body: dict,
) -> OutboxEvent:
    row = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload="{}",
        created_at=datetime.now(timezone.utc),
        published_at=None,
    )
    db.add(row)
    db.flush()
    row.payload = json.dumps(
        {"eventId": row.id, "type": event_type, **body}, default=str
    )
    return row


def relay_pending(db: Session, publisher: EventPublisher, limit: int = 50) -> int:
    rows = db.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.id)
        .limit(limit)
    ).all()
    sent = 0
    for row in rows:
        publisher.publish(str(row.aggregate_id), row.payload)
        row.published_at = datetime.now(timezone.utc)
        sent += 1
    return sent


def consume_notification(db: Session, payload: str) -> bool:
    """Store a delivered event once. Returns False when the event was already stored."""
    body = json.loads(payload)
    event_id = int(body["eventId"])
    existing = db.scalar(
        select(NotificationLog).where(NotificationLog.event_id == event_id)
    )
    if existing:
        return False
    db.add(
        NotificationLog(
            event_id=event_id,
            event_type=body.get("type", "UNKNOWN"),
            payload=payload,
            received_at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    return True
