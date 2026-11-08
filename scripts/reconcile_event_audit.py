#!/usr/bin/env python
"""Reconcile durable, unfinished audit records for event creation."""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from botocore.exceptions import BotoCoreError
from dotenv import load_dotenv
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.audit import (
    AuditPersistenceError,
    AuditOutboxStateError,
    complete_event_audit,
    reconciled_event_outcome,
)
from src.database import WriterSessionLocal
from src.models import EventAuditOutbox
from src.nosql import get_event


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--older-than-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.limit < 1 or args.older_than_seconds < 300:
        parser.error(
            "--limit debe ser positivo y --older-than-seconds debe ser al menos 300"
        )
    return args


def main() -> int:
    args = parse_args()
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=args.older_than_seconds
    )
    db = WriterSessionLocal()
    reconciled = 0
    skipped = 0
    pending_errors = 0
    try:
        operations = db.scalars(
            select(EventAuditOutbox)
            .where(
                EventAuditOutbox.status == "pending",
                EventAuditOutbox.requested_at <= cutoff,
            )
            .order_by(EventAuditOutbox.requested_at)
            .limit(args.limit)
        ).all()

        for operation in operations:
            try:
                stored_event = get_event(
                    operation.game_id,
                    operation.event_key,
                    consistent_read=True,
                )
                outcome = reconciled_event_outcome(
                    operation.operation_id,
                    stored_event,
                )
                complete_event_audit(
                    db,
                    operation_id=operation.operation_id,
                    actor_id=operation.actor_id,
                    game_id=operation.game_id,
                    event_key=operation.event_key,
                    outcome=outcome,
                )
                reconciled += 1
            except AuditOutboxStateError:
                db.rollback()
                skipped += 1
            except (AuditPersistenceError, BotoCoreError) as error:
                db.rollback()
                print(
                    "Could not reconcile an event audit entry "
                    f"({type(error).__name__}); it remains pending.",
                    file=sys.stderr,
                )
                pending_errors += 1
    finally:
        db.close()

    print(
        f"Reconciled {reconciled} pending event audit operation(s); "
        f"{skipped} were completed concurrently; {pending_errors} remain pending."
    )
    return 1 if pending_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
