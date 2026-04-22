"""
Kafka producer for the speed layer.

Reads generated events from sample_events.build_event() and publishes
them as JSON into the Kafka `raw_events` topic.

In production, the real crawler would call this producer (or its own
Kafka integration) instead of sample_events.

So using job_id as the key means:
all updates/events for the same job tend to stay in the same partition
ordering for that job is more stable
"""

import json
import os
import time

from dotenv import load_dotenv
from confluent_kafka import Producer

from sample_events import build_event

load_dotenv()

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
RAW_TOPIC = os.getenv("RAW_TOPIC", "raw_events")


def delivery_report(err, msg):
    """Callback invoked once per produced message to report delivery status."""
    if err is not None:
        print(f"Delivery failed: {err}")
    else:
        print(
            f"Produced topic={msg.topic()} partition={msg.partition()} "
            f"offset={msg.offset()}" # The message’s position inside that partition.
        )


def main():
    producer = Producer({"bootstrap.servers": BOOTSTRAP})

    while True:
        event = build_event()

        producer.produce(
            RAW_TOPIC,
            key=event["job_id"],
            value=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            callback=delivery_report,
        )
        producer.poll(0) # This keeps the producer alive and processes any delivery reports immediately.

        print(f"Sent event: {event['job_id']} | {event['title']} | {event['location_text']}")
        time.sleep(2) # Wait 2 seconds between events


if __name__ == "__main__":
    main()
