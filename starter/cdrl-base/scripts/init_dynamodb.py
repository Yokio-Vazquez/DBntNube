#!/usr/bin/env python
"""Create the local events table and load deterministic synthetic fixtures."""
import time

from botocore.exceptions import BotoCoreError, ClientError

from src.nosql import ensure_events_table, seed_fixture_events


def main():
    for attempt in range(30):
        try:
            table = ensure_events_table()
            seed_fixture_events(table)
            print("DynamoDB events table is ready with synthetic fixtures")
            return
        except (BotoCoreError, ClientError):
            if attempt == 29:
                raise
            time.sleep(1)


if __name__ == "__main__":
    main()