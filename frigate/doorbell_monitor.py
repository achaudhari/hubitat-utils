#!/usr/bin/env python3
"""
Multi-Vendor Video Doorbell Button Monitor
Monitors multiple doorbell cameras for button press events and publishes to MQTT
Supports multiple vendors via pluggable driver architecture
Works completely offline with local camera APIs
"""

import argparse
import sys
import time
import logging
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional
import yaml
import requests
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

class DoorbellDriver(ABC):
    """Abstract base class for doorbell camera drivers"""

    def __init__(self, name: str, config: Dict):
        """
        Initialize the driver

        Args:
            name: Name of this doorbell instance
            config: Configuration dictionary for this doorbell
        """
        self.name: str = name
        self.config: Dict = config
        self.ip: str = config.get('ip', '')
        self.username: str = config.get('username', 'admin')
        self.password: str = config.get('password', '')
        self.debounce_time: float = config.get('debounce_time', 5)
        self.last_event_time: float = 0
        self.session = requests.Session()

    @abstractmethod
    def login(self) -> bool:
        """
        Login to the doorbell camera

        Returns:
            True if login successful, False otherwise
        """

    @abstractmethod
    def check_doorbell_press(self) -> bool:
        """
        Check if doorbell button was pressed

        Returns:
            True if button was pressed (and debounce passed), False otherwise
        """

    def shutdown(self):
        """Clean up resources"""
        self.session.close()


class ReolinkDriver(DoorbellDriver):
    """Driver for Reolink doorbell cameras"""

    def __init__(self, name: str, config: Dict):
        super().__init__(name, config)
        self.token = None
        self.login_url = f"http://{self.ip}/api.cgi?cmd=Login"
        self.events_url = f"http://{self.ip}/api.cgi?cmd=GetEvents"
        self.debug_api = config.get('debug_api', False)
        self._logged_sample = False
        self._last_alarm_state = 0  # Track previous alarm state for edge detection

    def login(self) -> bool:
        """Login to Reolink camera"""
        try:
            login_data = [{
                "cmd": "Login",
                "action": 0,
                "param": {
                    "User": {
                        "userName": self.username,
                        "password": self.password
                    }
                }
            }]
            response = self.session.post(
                self.login_url,
                json=login_data,
                timeout=10
            )
            if response.status_code == 200:
                result = response.json()
                if result and len(result) > 0:
                    self.token = result[0].get('value', {}).get('Token', {}).get('name')
                    if self.token:
                        logger.info("[%s] Successfully logged in to Reolink doorbell", self.name)
                        return True

            logger.error("[%s] Failed to login to Reolink doorbell", self.name)
            return False

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("[%s] Login error: %s", self.name, e)
            return False

    def check_doorbell_press(self) -> bool:
        """Check for Reolink doorbell button press events"""
        try:
            events_data = [{
                "cmd": "GetEvents",
                "action": 1,
                "param": {
                    "channel": 0
                }
            }]

            params: Dict[str, str] = {}
            if self.token:
                params['token'] = self.token

            response = self.session.post(
                self.events_url,
                json=events_data,
                params=params,
                timeout=5
            )

            if response.status_code == 200:
                result = response.json()

                # Log the raw response for debugging
                if self.debug_api and not self._logged_sample:
                    logger.info("[%s] Sample API response: %s",
                                self.name, json.dumps(result, indent=2))
                    self._logged_sample = True

                # Check for active visitor/doorbell events
                # The API returns visitor.alarm_state: 1 when button is pressed, 0 otherwise
                if isinstance(result, list) and len(result) > 0:
                    value = result[0].get('value', {})

                    # Check if there's a visitor event
                    if 'visitor' in value:
                        visitor_data = value['visitor']
                        alarm_state = visitor_data.get('alarm_state', 0)

                        if self.debug_api:
                            logger.debug("[%s] Visitor alarm_state: %s (previous: %s)",
                                        self.name, alarm_state, self._last_alarm_state)

                        # Detect rising edge: transition from 0 to 1
                        # This prevents multiple triggers while alarm_state stays at 1
                        if alarm_state == 1 and self._last_alarm_state == 0:
                            current_time = time.time()

                            # Debounce: only trigger if enough time has passed since last event
                            if current_time - self.last_event_time > self.debounce_time:
                                logger.info("[%s] Doorbell button pressed!", self.name)
                                self.last_event_time = current_time
                                self._last_alarm_state = alarm_state
                                return True

                        # Update state for next iteration
                        self._last_alarm_state = alarm_state

            return False

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("[%s] Error checking doorbell events: %s", self.name, e)
            return False


# Driver registry
DRIVER_REGISTRY = {
    'reolink': ReolinkDriver,
    # Add more drivers here as they are implemented
    # 'tapo': TapoDriver,
}


class DoorbellMonitor:
    """Multi-vendor doorbell monitor with MQTT publishing"""

    def __init__(self, config_file: str):
        """
        Initialize the monitor with a YAML config file

        Args:
            config_file: Path to YAML configuration file
        """
        self.config = self._load_config(config_file)
        self.mqtt_client: Optional[mqtt.Client] = None
        self.drivers: List[DoorbellDriver] = []
        self.poll_interval = self.config.get('poll_interval', 1)
        self.max_reconnect_attempts = self.config.get('max_reconnect_attempts', 5)

    def _load_config(self, config_file: str) -> Dict:
        """Load and validate YAML configuration"""
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(os.path.expandvars(f.read()))

        # Validate config structure
        if 'mqtt' not in config:
            raise ValueError("Missing 'mqtt' section in config")
        if 'doorbells' not in config:
            raise ValueError("Missing 'doorbells' section in config")

        logger.info("Loaded configuration from %s", config_file)
        return config

    def _initialize_drivers(self):
        """Initialize doorbell drivers from config"""
        doorbells_config = self.config.get('doorbells', {})

        for name, doorbell_config in doorbells_config.items():
            driver_type = doorbell_config.get('driver', '').lower()
            if driver_type not in DRIVER_REGISTRY:
                logger.error("Unknown driver type '%s' for doorbell '%s'. Skipping.",
                             driver_type, name)
                continue
            try:
                driver_class = DRIVER_REGISTRY[driver_type]
                driver = driver_class(name, doorbell_config)
                self.drivers.append(driver)
                logger.info("Initialized %s driver for doorbell '%s'", driver_type, name)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Failed to initialize driver for doorbell '%s': %s", name, e)

    def connect_mqtt(self) -> bool:
        """Connect to MQTT broker"""
        try:
            mqtt_config = self.config['mqtt']
            broker = mqtt_config.get('broker', 'mqtt')
            port = mqtt_config.get('port', 1883)
            username = mqtt_config.get('username')
            password = mqtt_config.get('password')

            self.mqtt_client = mqtt.Client(client_id="doorbell-monitor")

            if username and password:
                self.mqtt_client.username_pw_set(username, password)

            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect

            logger.info("Connecting to MQTT broker at %s:%s", broker, port)
            self.mqtt_client.connect(broker, port, 60)
            self.mqtt_client.loop_start()
            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to connect to MQTT: %s", e)
            return False

    def _on_mqtt_connect(self, client, userdata, flags, rc):  # pylint: disable=unused-argument
        """MQTT connection callback"""
        if rc == 0:
            logger.info("Connected to MQTT broker successfully")
        else:
            logger.error("Failed to connect to MQTT broker with code %s", rc)

    def _on_mqtt_disconnect(self, client, userdata, rc):  # pylint: disable=unused-argument
        """MQTT disconnection callback"""
        if rc != 0:
            logger.warning("Unexpected MQTT disconnection (code %s). Reconnecting...", rc)

    def publish_doorbell_event(self, doorbell_name: str, topic_base: str):
        """
        Publish doorbell press event to MQTT

        Args:
            doorbell_name: Name of the doorbell that was pressed
            topic_base: MQTT topic base for this doorbell
        """
        if not self.mqtt_client:
            logger.error("MQTT client not connected")
            return

        try:
            # Publish ON message
            topic = f"{topic_base}/doorbell_press_status"
            self.mqtt_client.publish(topic, "ON", retain=False)
            logger.info("[%s] Published to %s: ON", doorbell_name, topic)
            # Brief delay then publish OFF
            time.sleep(0.1)
            self.mqtt_client.publish(topic, "OFF", retain=False)
            logger.info("[%s] Published to %s: OFF", doorbell_name, topic)
            # Also publish timestamp for reference
            timestamp_topic = f"{topic_base}/doorbell_press_ts"
            timestamp = datetime.now().isoformat()
            self.mqtt_client.publish(timestamp_topic, timestamp, retain=True)
            logger.info("[%s] Published to %s: %s", doorbell_name, timestamp_topic, timestamp)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("[%s] Error publishing to MQTT: %s", doorbell_name, e)

    def run(self):
        """Main monitoring loop"""
        logger.info("Starting Multi-Vendor Doorbell Monitor")

        # Initialize drivers
        self._initialize_drivers()
        if not self.drivers:
            raise RuntimeError("No doorbell drivers configured. Exiting.")
        # Connect to MQTT
        if not self.connect_mqtt():
            raise RuntimeError("Failed to connect to MQTT. Exiting.")
        # Login to all doorbells
        for driver in self.drivers:
            logger.info("Logging in to doorbell '%s'...", driver.name)
            if not driver.login():
                logger.error("Failed to login to doorbell '%s'. Will retry later.",
                             driver.name)

        # Monitor loop
        reconnect_attempts = {}
        for driver in self.drivers:
            reconnect_attempts[driver.name] = 0

        logger.info("Starting monitoring loop for %d doorbell(s)", len(self.drivers))
        while True:
            try:
                # Check each doorbell for button press
                for driver in self.drivers:
                    try:
                        if driver.check_doorbell_press():
                            # Get topic base from config
                            doorbell_config = self.config['doorbells'][driver.name]
                            topic_base = doorbell_config.get(
                                'mqtt_topic_base', f'frigate/{driver.name}')
                            self.publish_doorbell_event(driver.name, topic_base)
                        # Reset reconnect counter on successful check
                        reconnect_attempts[driver.name] = 0

                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error("[%s] Error checking doorbell: %s", driver.name, e)
                        reconnect_attempts[driver.name] += 1

                        if reconnect_attempts[driver.name] >= self.max_reconnect_attempts:
                            logger.error("[%s] Too many reconnect attempts (%s). Skipping.",
                                         driver.name, self.max_reconnect_attempts)
                            reconnect_attempts[driver.name] = 0
                        else:
                            logger.info("[%s] Attempting to reconnect (attempt %s/%s)...",
                                        driver.name,
                                        reconnect_attempts[driver.name],
                                        self.max_reconnect_attempts)
                            driver.login()

                # Sleep before next poll
                time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                logger.info("Shutting down gracefully...")
                if self.mqtt_client:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                for driver in self.drivers:
                    driver.shutdown()
                break

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error in monitoring loop: %s", e)
                time.sleep(5)

def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Doorbell Monitor - Notification and event management for doorbells'
    )
    parser.add_argument(
        '-c', '--config',
        default='doorbell-mon.yml',
        help='Path to configuration file (default: doorbell-mon.yml)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        monitor = DoorbellMonitor(args.config)
        monitor.run()
    except FileNotFoundError as e:
        logger.error("Configuration file not found: %s", e)
        sys.exit(1)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Fatal error: %s", e)
        sys.exit(1)


if __name__ == '__main__':
    main()
