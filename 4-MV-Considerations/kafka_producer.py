# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "clickhouse-connect",
#     "kafka-python",
#     "tabulate",
# ]
# ///
import json
import time
import random
from kafka import KafkaProducer
from datetime import datetime

def create_producer():
    """Create Kafka producer with JSON serialization"""
    return KafkaProducer(
        bootstrap_servers=['localhost:9092'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        key_serializer=lambda k: str(k).encode('utf-8') if k else None
    )

def generate_event(event_id):
    """Generate a random event"""
    return {
        'event_id': event_id,
        'value': random.randint(1, 1000),
        'timestamp': datetime.now().isoformat(),
        'category': random.choice(['A', 'B', 'C', 'D'])
    }

def main():
    print("Starting Kafka producer...")
    producer = create_producer()
    
    try:
        # Send events from 1 to 1000
        for event_id in range(1, 1001):
            event = generate_event(event_id)
            
            # Use event_id as key for proper partitioning
            producer.send(
                'events_topic',
                key=event_id,
                value=event
            )
            
            if event_id % 100 == 0:
                print(f"Sent {event_id} events...")
                producer.flush()
        
        producer.flush()
        print("\n✅ Successfully sent 1000 events!")
        
        # Print expected statistics for verification
        print("\n📊 Expected Statistics:")
        print("- Total Events: 1000")
        print("- Event IDs: 1 to 1000")
        print("- Values: Random between 1 and 1000")
        
    except KeyboardInterrupt:
        print("\n⚠️  Producer interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        producer.close()
        print("Producer closed.")

if __name__ == "__main__":
    main()