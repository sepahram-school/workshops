#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "faker",
#     "kafka-python",
#     "argparse",
# ]
# ///
"""
Advanced Kafka Stream Producer for RisingWave
Supports multiple scenarios: orders, IoT sensors, financial trades, user activity
"""

import json
import time
import random
import argparse
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from kafka import KafkaProducer
from faker import Faker

fake = Faker()


class StreamGenerator:
    """Base class for stream generators"""
    
    def __init__(self, bootstrap_servers: List[str] = ['localhost:9092']):
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: str(k).encode('utf-8') if k else None,
            acks='all',
            retries=3,
            max_in_flight_requests_per_connection=1,  # Ensure ordering
        )
    
    def send(self, topic: str, message: Dict[str, Any], key: str = None):
        """Send message to Kafka"""
        try:
            future = self.producer.send(topic, key=key, value=message)
            future.get(timeout=10)  # Block until sent
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def close(self):
        """Close producer"""
        self.producer.flush()
        self.producer.close()


class EcommerceGenerator(StreamGenerator):
    """Generate e-commerce orders"""
    
    ITEMS = [
        {'item_id': 1, 'name': 'Laptop', 'category': 'Electronics', 'base_price': 899.99},
        {'item_id': 2, 'name': 'Mouse', 'category': 'Accessories', 'base_price': 29.99},
        {'item_id': 3, 'name': 'Monitor', 'category': 'Electronics', 'base_price': 299.99},
        {'item_id': 4, 'name': 'Keyboard', 'category': 'Accessories', 'base_price': 79.99},
        {'item_id': 5, 'name': 'Headphones', 'category': 'Electronics', 'base_price': 149.99},
        {'item_id': 6, 'name': 'USB Cable', 'category': 'Accessories', 'base_price': 12.99},
        {'item_id': 7, 'name': 'Webcam', 'category': 'Electronics', 'base_price': 89.99},
        {'item_id': 8, 'name': 'Desk Lamp', 'category': 'Accessories', 'base_price': 39.99},
        {'item_id': 9, 'name': 'External SSD', 'category': 'Electronics', 'base_price': 199.99},
        {'item_id': 10, 'name': 'Mouse Pad', 'category': 'Accessories', 'base_price': 19.99},
    ]
    
    def generate(self) -> Dict[str, Any]:
        """Generate order message"""
        item = random.choice(self.ITEMS)
        
        qty = random.randint(1, 5)
        price = round(item['base_price'] * random.uniform(0.9, 1.1), 2)
        amount = round(qty * price, 2)
        
        return {
            'order_id': fake.unique.random_int(min=1000, max=999999),
            'user_id': fake.random_int(min=1, max=10000),
            'item_id': item['item_id'],
            'qty': qty,
            'price': price,
            'amount': amount,
            'discount_pct': random.choice([0.0, 0.0, 0.0, 5.0, 10.0, 15.0, 20.0]),
            'status': random.choice(['pending', 'processing', 'shipped', 'delivered', 'cancelled']),
            'ts': datetime.now(timezone.utc).isoformat(),
            
            # Additional fields for enrichment
            'customer_name': fake.name(),
            'customer_email': fake.email(),
            'shipping_address': {
                'street': fake.street_address(),
                'city': fake.city(),
                'state': fake.state_abbr(),
                'zip': fake.zipcode(),
                'country': 'US'
            },
            'payment_method': random.choice(['credit_card', 'debit_card', 'paypal', 'apple_pay']),
            'source_system': random.choice(['web', 'mobile_app', 'api']),
        }
    
    def run(self, topic: str = 'orders', rate: int = 10, duration: int = None):
        """Run continuous generation"""
        print(f"🛒 E-commerce order generator started (topic: {topic}, rate: {rate}/s)")
        
        count = 0
        start = time.time()
        
        try:
            while True:
                if duration and (time.time() - start) > duration:
                    break
                
                order = self.generate()
                self.send(topic, order, key=str(order['order_id']))
                
                count += 1
                if count % 100 == 0:
                    print(f"✅ Orders sent: {count}")
                
                time.sleep(1.0 / rate)
                
        except KeyboardInterrupt:
            print(f"\n⏸️  Stopped after {count} orders")
        finally:
            self.close()


class IoTSensorGenerator(StreamGenerator):
    """Generate IoT sensor data"""
    
    def __init__(self, *args, num_sensors: int = 50, **kwargs):
        super().__init__(*args, **kwargs)
        self.sensors = [f"sensor_{i:03d}" for i in range(num_sensors)]
        self.base_temps = {sensor: random.uniform(15, 25) for sensor in self.sensors}
    
    def generate(self) -> Dict[str, Any]:
        """Generate sensor reading"""
        sensor_id = random.choice(self.sensors)
        base_temp = self.base_temps[sensor_id]
        
        # Simulate temperature drift
        self.base_temps[sensor_id] += random.uniform(-0.5, 0.5)
        
        # Occasionally simulate anomalies
        if random.random() < 0.02:  # 2% anomaly rate
            temperature = base_temp + random.uniform(20, 40)
            status = 'ALERT'
        else:
            temperature = base_temp + random.uniform(-2, 2)
            status = 'NORMAL'
        
        return {
            'sensor_id': sensor_id,
            'temperature': round(temperature, 2),
            'humidity': round(random.uniform(30, 70), 2),
            'pressure': round(random.uniform(980, 1020), 2),
            'battery_level': round(random.uniform(70, 100), 1),
            'status': status,
            'location': {
                'lat': round(random.uniform(37.0, 38.0), 6),
                'lon': round(random.uniform(-122.5, -121.5), 6),
            },
            'ts': datetime.now(timezone.utc).isoformat(),
        }
    
    def run(self, topic: str = 'iot_sensors', rate: int = 50, duration: int = None):
        """Run continuous generation"""
        print(f"🌡️  IoT sensor generator started (topic: {topic}, rate: {rate}/s)")
        
        count = 0
        start = time.time()
        
        try:
            while True:
                if duration and (time.time() - start) > duration:
                    break
                
                reading = self.generate()
                self.send(topic, reading, key=reading['sensor_id'])
                
                count += 1
                if count % 500 == 0:
                    print(f"✅ Sensor readings sent: {count}")
                
                time.sleep(1.0 / rate)
                
        except KeyboardInterrupt:
            print(f"\n⏸️  Stopped after {count} readings")
        finally:
            self.close()


class FinancialTradeGenerator(StreamGenerator):
    """Generate financial trading data"""
    
    SYMBOLS = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'META', 'NVDA', 'AMD', 'INTC', 'NFLX']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prices = {symbol: random.uniform(100, 500) for symbol in self.SYMBOLS}
    
    def generate(self) -> Dict[str, Any]:
        """Generate trade"""
        symbol = random.choice(self.SYMBOLS)
        
        # Price movement
        self.prices[symbol] *= random.uniform(0.995, 1.005)
        
        price = round(self.prices[symbol], 2)
        volume = random.randint(100, 10000)
        
        return {
            'trade_id': fake.unique.random_int(min=1000000, max=9999999),
            'symbol': symbol,
            'price': price,
            'volume': volume,
            'side': random.choice(['BUY', 'SELL']),
            'exchange': random.choice(['NYSE', 'NASDAQ', 'CBOE']),
            'trader_id': f"trader_{random.randint(1, 1000):04d}",
            'ts': datetime.now(timezone.utc).isoformat(),
        }
    
    def run(self, topic: str = 'trades', rate: int = 100, duration: int = None):
        """Run continuous generation"""
        print(f"💹 Financial trade generator started (topic: {topic}, rate: {rate}/s)")
        
        count = 0
        start = time.time()
        
        try:
            while True:
                if duration and (time.time() - start) > duration:
                    break
                
                trade = self.generate()
                self.send(topic, trade, key=trade['symbol'])
                
                count += 1
                if count % 1000 == 0:
                    print(f"✅ Trades sent: {count}")
                
                time.sleep(1.0 / rate)
                
        except KeyboardInterrupt:
            print(f"\n⏸️  Stopped after {count} trades")
        finally:
            self.close()


class UserActivityGenerator(StreamGenerator):
    """Generate user activity events"""
    
    EVENTS = ['page_view', 'click', 'search', 'add_to_cart', 'purchase', 'login', 'logout']
    PAGES = ['/home', '/products', '/cart', '/checkout', '/profile', '/help']
    
    def generate(self) -> Dict[str, Any]:
        """Generate user activity event"""
        event_type = random.choice(self.EVENTS)
        
        event = {
            'event_id': fake.uuid4(),
            'user_id': fake.random_int(min=1, max=10000),
            'session_id': fake.uuid4(),
            'event_type': event_type,
            'page_url': random.choice(self.PAGES),
            'referrer': random.choice([None, 'google.com', 'facebook.com', 'twitter.com']),
            'device': random.choice(['desktop', 'mobile', 'tablet']),
            'browser': random.choice(['Chrome', 'Firefox', 'Safari', 'Edge']),
            'ip_address': fake.ipv4(),
            'country': fake.country_code(),
            'ts': datetime.now(timezone.utc).isoformat(),
        }
        
        # Add event-specific data
        if event_type == 'search':
            event['search_query'] = fake.sentence(nb_words=3)
        elif event_type in ['add_to_cart', 'purchase']:
            event['product_id'] = random.randint(1, 100)
            event['price'] = round(random.uniform(10, 500), 2)
        
        return event
    
    def run(self, topic: str = 'user_activity', rate: int = 20, duration: int = None):
        """Run continuous generation"""
        print(f"👤 User activity generator started (topic: {topic}, rate: {rate}/s)")
        
        count = 0
        start = time.time()
        
        try:
            while True:
                if duration and (time.time() - start) > duration:
                    break
                
                event = self.generate()
                self.send(topic, event, key=str(event['user_id']))
                
                count += 1
                if count % 200 == 0:
                    print(f"✅ Events sent: {count}")
                
                time.sleep(1.0 / rate)
                
        except KeyboardInterrupt:
            print(f"\n⏸️  Stopped after {count} events")
        finally:
            self.close()


class ReturnsGenerator(StreamGenerator):
    """Generate return/refund events for e-commerce orders"""
    
    def generate(self) -> Dict[str, Any]:
        """Generate return message"""
        return {
            'return_id': fake.unique.random_int(min=1000, max=999999),
            'order_id': fake.random_int(min=1000, max=999999),  # Reference to existing order
            'refund_amount': round(random.uniform(10, 500), 2),
            'reason': random.choice(['defective', 'wrong_item', 'changed_mind', 'too_late']),
            'ts': datetime.now(timezone.utc).isoformat(),
        }
    
    def run(self, topic: str = 'returns', rate: int = 5, duration: int = None):
        """Run continuous generation"""
        print(f"↩️  Returns generator started (topic: {topic}, rate: {rate}/s)")
        
        count = 0
        start = time.time()
        
        try:
            while True:
                if duration and (time.time() - start) > duration:
                    break
                
                return_event = self.generate()
                self.send(topic, return_event, key=str(return_event['return_id']))
                
                count += 1
                if count % 100 == 0:
                    print(f"✅ Returns sent: {count}")
                
                time.sleep(1.0 / rate)
                
        except KeyboardInterrupt:
            print(f"\n⏸️  Stopped after {count} returns")
        finally:
            self.close()





def main():
    """Main entry point with command line arguments or interactive menu"""
    
    import sys
    
    # Check if command line arguments are provided
    if len(sys.argv) > 1:
        # Use command line arguments
        parser = argparse.ArgumentParser(description='Kafka Stream Generator for RisingWave')
        parser.add_argument('scenario', choices=['orders', 'iot', 'trades', 'activity', 'returns'], 
                           help='Data generation scenario')
        parser.add_argument('--rate', type=int, default=None, 
                           help='Records per second (default: scenario-specific)')
        parser.add_argument('--duration', type=int, default=None, 
                           help='Duration in seconds (default: unlimited)')
        parser.add_argument('--topic', type=str, default=None, 
                           help='Kafka topic name (default: scenario-specific)')
        
        args = parser.parse_args()
        
        print("=" * 60)
        print("Kafka Stream Generator for RisingWave")
        print("=" * 60)
        print(f"🚀 Starting {args.scenario} scenario...")
        print(f"📊 Target rate: {args.rate or 'default'} records/second")
        print(f"📍 Duration: {args.duration or 'unlimited'} seconds")
        print(f"📝 Topic: {args.topic or args.scenario}")
        print(f"\n{'='*60}\n")
        
        if args.scenario == 'orders':
            gen = EcommerceGenerator()
            rate = args.rate if args.rate else 10
            topic = args.topic if args.topic else 'orders'
            gen.run(topic=topic, rate=rate, duration=args.duration)
        
        elif args.scenario == 'iot':
            gen = IoTSensorGenerator(num_sensors=50)
            rate = args.rate if args.rate else 50
            topic = args.topic if args.topic else 'iot_sensors'
            gen.run(topic=topic, rate=rate, duration=args.duration)
        
        elif args.scenario == 'trades':
            gen = FinancialTradeGenerator()
            rate = args.rate if args.rate else 100
            topic = args.topic if args.topic else 'trades'
            gen.run(topic=topic, rate=rate, duration=args.duration)
        
        elif args.scenario == 'activity':
            gen = UserActivityGenerator()
            rate = args.rate if args.rate else 20
            topic = args.topic if args.topic else 'user_activity'
            gen.run(topic=topic, rate=rate, duration=args.duration)
        
        elif args.scenario == 'returns':
            gen = ReturnsGenerator()
            rate = args.rate if args.rate else 5
            topic = args.topic if args.topic else 'returns'
            gen.run(topic=topic, rate=rate, duration=args.duration)
        
        else:
            print("Invalid scenario choice")
    else:
        # Show interactive menu
        print("=" * 60)
        print("Kafka Stream Generator for RisingWave")
        print("=" * 60)
        print("No command line arguments provided. Starting interactive mode...")
        print()
        
        # Show scenario options
        scenarios = {
            '1': ('orders', 'E-commerce orders'),
            '2': ('iot', 'IoT sensor data'),
            '3': ('trades', 'Financial trading data'),
            '4': ('activity', 'User activity events'),
            '5': ('returns', 'Return/refund events')
        }
        
        print("Available scenarios:")
        for key, (scenario, description) in scenarios.items():
            print(f"  {key}. {description} ({scenario})")
        
        # Get scenario choice
        while True:
            choice = input("\nSelect a scenario (1-5): ").strip()
            if choice in scenarios:
                scenario, description = scenarios[choice]
                break
            else:
                print("Invalid choice. Please select 1-5.")
        
        # Get rate
        while True:
            rate_input = input(f"Enter records per second (default: {get_default_rate(scenario)}): ").strip()
            if rate_input == "":
                rate = None
                break
            try:
                rate = int(rate_input)
                if rate > 0:
                    break
                else:
                    print("Rate must be a positive number.")
            except ValueError:
                print("Please enter a valid number.")
        
        # Get duration
        while True:
            duration_input = input("Enter duration in seconds (default: unlimited): ").strip()
            if duration_input == "":
                duration = None
                break
            try:
                duration = int(duration_input)
                if duration > 0:
                    break
                else:
                    print("Duration must be a positive number.")
            except ValueError:
                print("Please enter a valid number.")
        
        # Get topic name
        topic_input = input(f"Enter topic name (default: {scenario}): ").strip()
        topic = topic_input if topic_input else None
        
        print("\n" + "=" * 60)
        print("Configuration Summary:")
        print(f"🚀 Scenario: {description} ({scenario})")
        print(f"📊 Target rate: {rate or get_default_rate(scenario)} records/second")
        print(f"📍 Duration: {duration or 'unlimited'} seconds")
        print(f"📝 Topic: {topic or scenario}")
        print("=" * 60)
        
        # Start the generator
        if scenario == 'orders':
            gen = EcommerceGenerator()
            rate = rate if rate else 10
            topic = topic if topic else 'orders'
            gen.run(topic=topic, rate=rate, duration=duration)
        
        elif scenario == 'iot':
            gen = IoTSensorGenerator(num_sensors=50)
            rate = rate if rate else 50
            topic = topic if topic else 'iot_sensors'
            gen.run(topic=topic, rate=rate, duration=duration)
        
        elif scenario == 'trades':
            gen = FinancialTradeGenerator()
            rate = rate if rate else 100
            topic = topic if topic else 'trades'
            gen.run(topic=topic, rate=rate, duration=duration)
        
        elif scenario == 'activity':
            gen = UserActivityGenerator()
            rate = rate if rate else 20
            topic = topic if topic else 'user_activity'
            gen.run(topic=topic, rate=rate, duration=duration)
        
        elif scenario == 'returns':
            gen = ReturnsGenerator()
            rate = rate if rate else 5
            topic = topic if topic else 'returns'
            gen.run(topic=topic, rate=rate, duration=duration)
        
        elif scenario == 'order_updates':
            # Get max order ID for updates
            while True:
                max_order_input = input("Enter maximum order ID for updates (default: 999999): ").strip()
                if max_order_input == "":
                    max_order_id = 999999
                    break
                try:
                    max_order_id = int(max_order_input)
                    if max_order_id > 0:
                        break
                    else:
                        print("Max order ID must be a positive number.")
                except ValueError:
                    print("Please enter a valid number.")
            
            # Get update interval
            while True:
                interval_input = input("Enter update interval in seconds (default: 30): ").strip()
                if interval_input == "":
                    update_interval = 30
                    break
                try:
                    update_interval = int(interval_input)
                    if update_interval > 0:
                        break
                    else:
                        print("Update interval must be a positive number.")
                except ValueError:
                    print("Please enter a valid number.")
            
            gen = OrderUpdateGenerator(max_order_id=max_order_id, update_interval=update_interval)
            rate = rate if rate else 10
            topic = topic if topic else 'orders'
            gen.run(topic=topic, rate=rate, duration=duration)


def get_default_rate(scenario: str) -> int:
    """Get default rate for a scenario"""
    defaults = {
        'orders': 10,
        'iot': 50,
        'trades': 100,
        'activity': 20,
        'returns': 5
    }
    return defaults.get(scenario, 10)


if __name__ == '__main__':
    main()