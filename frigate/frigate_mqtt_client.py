#!/usr/bin/env python3
"""
Frigate MQTT Client

A comprehensive Python client for interacting with Frigate NVR via MQTT.
Supports all commands and event notifications as documented in:
https://docs.frigate.video/integrations/mqtt/
"""

import json
import logging
import threading
import time
from typing import Callable, Dict, Optional, List, Any
from dataclasses import dataclass
from enum import Enum

import paho.mqtt.client as mqtt


class FrigateCommand(Enum):
    """Enumeration of available Frigate MQTT commands"""
    # Camera enable/disable commands
    CAMERA_ENABLE = "ON"
    CAMERA_DISABLE = "OFF"

    # Audio detection commands
    AUDIO_ENABLE = "ON"
    AUDIO_DISABLE = "OFF"

    # Detection commands
    DETECT_ENABLE = "ON"
    DETECT_DISABLE = "OFF"

    # Snapshot commands
    SNAPSHOTS_ENABLE = "ON"
    SNAPSHOTS_DISABLE = "OFF"

    # Motion detection commands
    MOTION_ENABLE = "ON"
    MOTION_DISABLE = "OFF"
    MOTION_IMPROVE_CONTRAST = "improve_contrast"

    # Recording commands
    RECORDING_ENABLE = "ON"
    RECORDING_DISABLE = "OFF"

    # PTZ commands
    PTZ_AUTOTRACK_ENABLE = "ON"
    PTZ_AUTOTRACK_DISABLE = "OFF"

    # System commands
    RESTART = "restart"


class FrigateEventType(Enum):
    """Enumeration of Frigate event types"""
    NEW = "new"
    UPDATE = "update"
    END = "end"


@dataclass
class FrigateEventData:
    """Event data for before/after states in Frigate events."""
    # Unique event identifier
    id: str
    # Camera name that detected the event
    camera: str
    # Detected object label (person, car, dog, etc.)
    label: str
    # Current detection confidence score (0.0-1.0)
    score: float
    # Bounding box coordinates [x1, y1, x2, y2]
    box: List[int]
    # Area of the bounding box in pixels
    area: int
    # Unix timestamp when event started
    start_time: float
    # Unix timestamp when event ended (None if active)
    end_time: Optional[float]
    # Highest confidence score achieved during event
    top_score: float
    # Whether event is marked as false positive
    false_positive: bool
    # Zones the object is currently in
    current_zones: List[str]
    # All zones the object has entered
    entered_zones: List[str]
    # Whether a snapshot has been saved
    has_snapshot: bool
    # Whether a video clip has been saved
    has_clip: bool
    # Whether object is currently moving (opposite of stationary)
    active: bool
    # Whether object is stationary
    stationary: bool
    # Sub-label [name, score] from facial recognition or None
    sub_label: Optional[List[Any]]
    # Detected attributes with their top scores (e.g., {"face": 0.86})
    attributes: Dict[str, float]
    # Recognized license plate text
    recognized_license_plate: Optional[str] = None
    # License plate recognition confidence
    recognized_license_plate_score: Optional[float] = None
    # Current speed (mph or kph)
    current_estimated_speed: Optional[float] = None
    # Average speed over event duration
    average_estimated_speed: Optional[float] = None
    # Direction of travel in degrees (0-360)
    velocity_angle: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'FrigateEventData':
        """Create FrigateEventData from dictionary."""
        return cls(
            id=data.get('id', ''),
            camera=data.get('camera', ''),
            label=data.get('label', ''),
            score=data.get('score', 0.0),
            box=data.get('box', []),
            area=data.get('area', 0),
            start_time=data.get('start_time', 0.0),
            end_time=data.get('end_time'),
            top_score=data.get('top_score', 0.0),
            false_positive=data.get('false_positive', False),
            current_zones=data.get('current_zones', []),
            entered_zones=data.get('entered_zones', []),
            has_snapshot=data.get('has_snapshot', False),
            has_clip=data.get('has_clip', False),
            active=data.get('active', True),
            stationary=data.get('stationary', False),
            sub_label=data.get('sub_label'),
            attributes=data.get('attributes', {}),
            recognized_license_plate=data.get('recognized_license_plate'),
            recognized_license_plate_score=data.get('recognized_license_plate_score'),
            current_estimated_speed=data.get('current_estimated_speed'),
            average_estimated_speed=data.get('average_estimated_speed'),
            velocity_angle=data.get('velocity_angle'),
        )


@dataclass
class FrigateEvent:
    """Frigate event with before and after states."""
    event_type: FrigateEventType  # Event type: NEW, UPDATE, or END
    before: Optional[FrigateEventData]  # Previous state (None for new events)
    after: FrigateEventData  # Current state

    @classmethod
    def from_dict(cls, data: Dict) -> 'FrigateEvent':
        """Create FrigateEvent from dictionary."""
        before = None
        if 'before' in data and data['before']:
            before = FrigateEventData.from_dict(data['before'])
        after = FrigateEventData.from_dict(data['after'])

        # Parse event type string to enum
        event_type_str = data.get('type', 'update').lower()
        try:
            event_type = FrigateEventType(event_type_str)
        except ValueError:
            event_type = FrigateEventType.UPDATE  # Default to UPDATE if unknown

        return cls(
            event_type=event_type,
            before=before,
            after=after
        )


@dataclass
class CameraInfo:
    """Information about a Frigate camera."""
    # Camera name
    name: str
    # Whether camera is enabled
    enabled: Optional[str] = None
    # Detection state (ON/OFF)
    detect_state: Optional[str] = None
    # Motion detection state (ON/OFF)
    motion_state: Optional[str] = None
    # Audio detection state (ON/OFF)
    audio_state: Optional[str] = None
    # Recordings state (ON/OFF)
    recordings_state: Optional[str] = None
    # Snapshots state (ON/OFF)
    snapshots_state: Optional[str] = None
    # Motion threshold value
    motion_threshold: Optional[str] = None
    # Motion contour area value
    motion_contour_area: Optional[str] = None
    # Doorbell press status (ON/OFF)
    doorbell_press_state: Optional[str] = None
    # Camera FPS from stats
    camera_fps: Optional[float] = None
    # Detection FPS from stats
    detection_fps: Optional[float] = None
    # Process FPS from stats
    process_fps: Optional[float] = None
    # Skip FPS from stats
    skipped_fps: Optional[float] = None
    # Last time stats were updated
    last_stats_update: Optional[float] = None


class FrigateMQTTClient:
    """
    A comprehensive MQTT client for Frigate NVR.

    Provides methods to:
    - Send commands to Frigate (recordings, detection, snapshots, PTZ, etc.)
    - Subscribe to and handle Frigate events
    - Monitor camera availability and statistics
    """

    def __init__(
        self,
        mqtt_host: str,
        mqtt_port: int = 1883,
        mqtt_username: Optional[str] = None,
        mqtt_password: Optional[str] = None,
        client_id: Optional[str] = None,
        base_topic: str = "frigate"
    ):
        """
        Initialize Frigate MQTT client.

        Args:
            mqtt_host: MQTT broker hostname/IP
            mqtt_port: MQTT broker port (default: 1883)
            mqtt_username: Optional MQTT username
            mqtt_password: Optional MQTT password
            client_id: Optional MQTT client ID
            base_topic: Base topic prefix for Frigate (default: 'frigate')
        """
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.base_topic = base_topic

        # Initialize MQTT client
        self.client = mqtt.Client(client_id=client_id or f"frigate_client_{int(time.time())}")

        if mqtt_username and mqtt_password:
            self.client.username_pw_set(mqtt_username, mqtt_password)

        # Set up callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        # Event handlers
        self._event_handlers: Dict[str, List[Callable]] = {
            'events': [],
            'availability': [],
            'stats': [],
            'detection': [],
            'motion': [],
            'audio': [],
            'enabled': [],
            'recordings': [],
            'snapshots': [],
            'motion_threshold': [],
            'motion_contour_area': [],
            'doorbell_press': [],
        }

        # Camera tracking
        self._cameras: Dict[str, CameraInfo] = {}
        self._stats_received = threading.Event()

        self._connected = False
        self._logger = logging.getLogger(__name__)

    # ==================== Connection Management ====================

    def connect(self, discovery_timeout: float = 10.0) -> bool:
        """
        Connect to MQTT broker and wait for camera discovery.

        Args:
            discovery_timeout: Timeout in seconds to wait for camera discovery (default: 10.0)
                              Discovery completes when either stats arrive or cameras are
                              found from state messages, whichever comes first.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self._logger.info("Connecting to MQTT broker at %s:%d", self.mqtt_host, self.mqtt_port)
            self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
            self.client.loop_start()

            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self._connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)

            if not self._connected:
                return False

            # Give a small grace period for subscriptions to complete
            time.sleep(0.2)

            # Wait for initial stats message or camera discovery
            self._logger.info("Waiting for camera discovery (timeout: %.1fs)...",
                              discovery_timeout)

            # Check periodically if cameras have been discovered
            check_interval = 0.1
            elapsed = 0.0
            while elapsed < discovery_timeout:
                if self._stats_received.wait(check_interval):
                    self._logger.info("Stats received, %d camera(s) discovered",
                                      len(self._cameras))
                    break
                elif len(self._cameras) > 0:
                    self._logger.info("Discovered %d camera(s) from state messages",
                                      len(self._cameras))
                    self._logger.debug("Stats not received, but cameras found from state topics")
                    break
                elapsed += check_interval
            else:
                if len(self._cameras) == 0:
                    self._logger.warning("No cameras discovered within timeout")
                    self._logger.warning("Cameras will be discovered when messages arrive")

            return self._connected
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Failed to connect to MQTT broker: %s", e)
            return False

    def disconnect(self):
        """Disconnect from MQTT broker."""
        self._logger.info("Disconnecting from MQTT broker")
        self.client.loop_stop()
        self.client.disconnect()
        self._connected = False

    def is_connected(self) -> bool:
        """Check if client is connected to MQTT broker."""
        return self._connected

    # ==================== MQTT Callbacks ====================

    def _on_connect(self, client, userdata, flags, rc): # pylint: disable=unused-argument
        """Callback when connected to MQTT broker."""
        if rc == 0:
            self._logger.info("Connected to MQTT broker successfully")
            self._connected = True
            # Subscribe to all Frigate topics
            self._logger.debug("Subscribing to Frigate topics...")
            self._subscribe_all()
            self._logger.debug("Subscriptions complete")
        else:
            self._logger.error("Failed to connect to MQTT broker, return code: %d", rc)
            self._connected = False

    def _on_disconnect(self, client, userdata, rc): # pylint: disable=unused-argument
        """Callback when disconnected from MQTT broker."""
        self._logger.warning("Disconnected from MQTT broker, return code: %d", rc)
        self._connected = False

    def _on_message(self, client, userdata, msg): # pylint: disable=unused-argument
        """Callback when message received from MQTT broker."""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')

            self._logger.debug("Received message on topic %s: %s", topic, payload)

            # Parse topic to determine message type
            topic_parts = topic.split('/')

            if 'events' in topic_parts:
                self._handle_event_message(topic, payload)
            elif 'available' in topic_parts:
                self._handle_availability_message(topic, payload)
            elif 'stats' in topic_parts:
                self._handle_stats_message(topic, payload)
            elif topic.endswith('/detect/state'):
                self._handle_detection_state(topic, payload)
            elif topic.endswith('/motion/state'):
                self._handle_motion_state(topic, payload)
            elif topic.endswith('/audio/state'):
                self._handle_audio_state(topic, payload)
            elif topic.endswith('/enabled/state'):
                self._handle_enabled_state(topic, payload)
            elif topic.endswith('/recordings/state'):
                self._handle_recordings_state(topic, payload)
            elif topic.endswith('/snapshots/state'):
                self._handle_snapshots_state(topic, payload)
            elif topic.endswith('/motion_threshold/state'):
                self._handle_motion_threshold_state(topic, payload)
            elif topic.endswith('/motion_contour_area/state'):
                self._handle_motion_contour_area_state(topic, payload)
            elif topic.endswith('/doorbell_press/state'):
                self._handle_doorbell_press_state(topic, payload)

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Error handling message: %s", e)

    def _subscribe_all(self):
        """Subscribe to all relevant Frigate MQTT topics."""
        topics = [
            f"{self.base_topic}/events",
            f"{self.base_topic}/+/events",
            f"{self.base_topic}/available",
            f"{self.base_topic}/stats",
            f"{self.base_topic}/+/detect/state",
            f"{self.base_topic}/+/motion/state",
            f"{self.base_topic}/+/audio/state",
            f"{self.base_topic}/+/enabled/state",
            f"{self.base_topic}/+/recordings/state",
            f"{self.base_topic}/+/snapshots/state",
            f"{self.base_topic}/+/motion_threshold/state",
            f"{self.base_topic}/+/motion_contour_area/state",
            f"{self.base_topic}/+/doorbell_press/state",
        ]

        for topic in topics:
            self.client.subscribe(topic)
            self._logger.debug("Subscribed to topic: %s", topic)

    # ==================== Event Handlers ====================

    def _handle_event_message(self, topic: str, payload: str): # pylint: disable=unused-argument
        """Handle event messages from Frigate."""
        try:
            event_dict = json.loads(payload)
            event = FrigateEvent.from_dict(event_dict)
            for handler in self._event_handlers['events']:
                handler(event)
        except json.JSONDecodeError:
            self._logger.error("Failed to decode event message: %s", payload)
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Failed to parse event message: %s", e)

    def _handle_availability_message(self, topic: str, payload: str): # pylint: disable=unused-argument
        """Handle availability messages from Frigate."""
        available = payload.lower() == 'online'
        for handler in self._event_handlers['availability']:
            handler(available)

    def _handle_stats_message(self, topic: str, payload: str):
        """Handle statistics messages from Frigate."""
        self._logger.debug("Received stats message on topic: %s", topic)
        try:
            stats_data = json.loads(payload)

            # Update camera information from stats
            if 'cameras' in stats_data:
                current_time = time.time()
                camera_count = len(stats_data['cameras'])
                self._logger.debug("Processing stats for %d camera(s)", camera_count)
                for camera_name, cam_stats in stats_data['cameras'].items():
                    if camera_name not in self._cameras:
                        self._cameras[camera_name] = CameraInfo(name=camera_name)
                        self._logger.debug("Discovered new camera: %s", camera_name)

                    cam_info = self._cameras[camera_name]
                    cam_info.camera_fps = cam_stats.get('camera_fps')
                    cam_info.detection_fps = cam_stats.get('detection_fps')
                    cam_info.process_fps = cam_stats.get('process_fps')
                    cam_info.skipped_fps = cam_stats.get('skipped_fps')
                    cam_info.last_stats_update = current_time

            # Signal that stats have been received
            self._stats_received.set()

            for handler in self._event_handlers['stats']:
                handler(stats_data)
        except json.JSONDecodeError:
            self._logger.error("Failed to decode stats message: %s", payload)

    def _handle_detection_state(self, topic: str, payload: str):
        """Handle detection state messages."""
        camera = topic.split('/')[1]
        state = payload

        # Update camera info
        if camera not in self._cameras:
            self._cameras[camera] = CameraInfo(name=camera)
        self._cameras[camera].detect_state = state

        for handler in self._event_handlers['detection']:
            handler(camera, state)

    def _handle_motion_state(self, topic: str, payload: str):
        """Handle motion state messages."""
        camera = topic.split('/')[1]
        state = payload

        # Update camera info
        if camera not in self._cameras:
            self._cameras[camera] = CameraInfo(name=camera)
        self._cameras[camera].motion_state = state

        for handler in self._event_handlers['motion']:
            handler(camera, state)

    def _handle_audio_state(self, topic: str, payload: str):
        """Handle audio state messages."""
        camera = topic.split('/')[1]
        state = payload

        # Update camera info
        if camera not in self._cameras:
            self._cameras[camera] = CameraInfo(name=camera)
        self._cameras[camera].audio_state = state

        for handler in self._event_handlers['audio']:
            handler(camera, state)

    def _handle_enabled_state(self, topic: str, payload: str):
        """Handle camera enabled state messages."""
        camera = topic.split('/')[1]
        state = payload

        # Update camera info
        if camera not in self._cameras:
            self._cameras[camera] = CameraInfo(name=camera)
        self._cameras[camera].enabled = state

        for handler in self._event_handlers['enabled']:
            handler(camera, state)

    def _handle_recordings_state(self, topic: str, payload: str):
        """Handle recordings state messages."""
        camera = topic.split('/')[1]
        state = payload

        # Update camera info
        if camera not in self._cameras:
            self._cameras[camera] = CameraInfo(name=camera)
        self._cameras[camera].recordings_state = state

        for handler in self._event_handlers['recordings']:
            handler(camera, state)

    def _handle_snapshots_state(self, topic: str, payload: str):
        """Handle snapshots state messages."""
        camera = topic.split('/')[1]
        state = payload

        # Update camera info
        if camera not in self._cameras:
            self._cameras[camera] = CameraInfo(name=camera)
        self._cameras[camera].snapshots_state = state

        for handler in self._event_handlers['snapshots']:
            handler(camera, state)

    def _handle_motion_threshold_state(self, topic: str, payload: str):
        """Handle motion threshold state messages."""
        camera = topic.split('/')[1]
        state = payload

        # Update camera info
        if camera not in self._cameras:
            self._cameras[camera] = CameraInfo(name=camera)
        self._cameras[camera].motion_threshold = state

        for handler in self._event_handlers['motion_threshold']:
            handler(camera, state)

    def _handle_motion_contour_area_state(self, topic: str, payload: str):
        """Handle motion contour area state messages."""
        camera = topic.split('/')[1]
        state = payload

        # Update camera info
        if camera not in self._cameras:
            self._cameras[camera] = CameraInfo(name=camera)
        self._cameras[camera].motion_contour_area = state

        for handler in self._event_handlers['motion_contour_area']:
            handler(camera, state)

    def _handle_doorbell_press_state(self, topic: str, payload: str):
        """Handle doorbell press state messages."""
        camera = topic.split('/')[1]
        state = payload

        # Update camera info
        if camera not in self._cameras:
            self._cameras[camera] = CameraInfo(name=camera)
        self._cameras[camera].doorbell_press_state = state

        # Call registered handlers
        for handler in self._event_handlers['doorbell_press']:
            handler(camera, state)

    # ==================== Event Subscription ====================

    def on_event(self, handler: Callable[[FrigateEvent], None]):
        """
        Register handler for Frigate events.

        Args:
            handler: Callback function that receives FrigateEvent object
        """
        self._event_handlers['events'].append(handler)

    def on_availability_change(self, handler: Callable[[bool], None]):
        """
        Register handler for Frigate availability changes.

        Args:
            handler: Callback function that receives availability status (bool)
        """
        self._event_handlers['availability'].append(handler)

    def on_stats_update(self, handler: Callable[[Dict], None]):
        """
        Register handler for Frigate statistics updates.

        Args:
            handler: Callback function that receives stats data dict
        """
        self._event_handlers['stats'].append(handler)

    def on_detection_state_change(self, handler: Callable[[str, str], None]):
        """
        Register handler for detection state changes.

        Args:
            handler: Callback function that receives (camera_name, state)
        """
        self._event_handlers['detection'].append(handler)

    def on_motion_state_change(self, handler: Callable[[str, str], None]):
        """
        Register handler for motion detection state changes.

        Args:
            handler: Callback function that receives (camera_name, state)
        """
        self._event_handlers['motion'].append(handler)

    def on_audio_state_change(self, handler: Callable[[str, str], None]):
        """
        Register handler for audio detection state changes.

        Args:
            handler: Callback function that receives (camera_name, state)
        """
        self._event_handlers['audio'].append(handler)

    def on_enabled_state_change(self, handler: Callable[[str, str], None]):
        """
        Register handler for camera enabled state changes.

        Args:
            handler: Callback function that receives (camera_name, state)
        """
        self._event_handlers['enabled'].append(handler)

    def on_recordings_state_change(self, handler: Callable[[str, str], None]):
        """
        Register handler for recordings state changes.

        Args:
            handler: Callback function that receives (camera_name, state)
        """
        self._event_handlers['recordings'].append(handler)

    def on_snapshots_state_change(self, handler: Callable[[str, str], None]):
        """
        Register handler for snapshots state changes.

        Args:
            handler: Callback function that receives (camera_name, state)
        """
        self._event_handlers['snapshots'].append(handler)

    def on_motion_threshold_state_change(self, handler: Callable[[str, str], None]):
        """
        Register handler for motion threshold state changes.

        Args:
            handler: Callback function that receives (camera_name, state)
        """
        self._event_handlers['motion_threshold'].append(handler)

    def on_motion_contour_area_state_change(self, handler: Callable[[str, str], None]):
        """
        Register handler for motion contour area state changes.

        Args:
            handler: Callback function that receives (camera_name, state)
        """
        self._event_handlers['motion_contour_area'].append(handler)

    def on_doorbell_press(self, handler: Callable[[str, str], None]):
        """
        Register handler for doorbell press events.

        Args:
            handler: Callback function that receives (camera_name, state)
        """
        self._event_handlers['doorbell_press'].append(handler)

    # ==================== Command Methods ====================

    def _publish_command(self, topic: str, payload: str, retain: bool = False):
        """
        Publish a command to Frigate.

        Args:
            topic: MQTT topic
            payload: Message payload
            retain: Whether to retain the message
        """
        if not self._connected:
            self._logger.error("Cannot publish command: not connected to MQTT broker")
            return False

        self._logger.info("Publishing command to %s: %s", topic, payload)
        result = self.client.publish(topic, payload, retain=retain)
        return result.rc == mqtt.MQTT_ERR_SUCCESS

    # Recording commands

    def enable_recording(self, camera: str) -> bool:
        """
        Enable recording on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/recordings/set"
        return self._publish_command(topic, FrigateCommand.RECORDING_ENABLE.value)

    def disable_recording(self, camera: str) -> bool:
        """
        Disable recording on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/recordings/set"
        return self._publish_command(topic, FrigateCommand.RECORDING_DISABLE.value)

    # Detection commands

    def enable_detection(self, camera: str) -> bool:
        """
        Enable object detection on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/detect/set"
        return self._publish_command(topic, FrigateCommand.DETECT_ENABLE.value)

    def disable_detection(self, camera: str) -> bool:
        """
        Disable object detection on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/detect/set"
        return self._publish_command(topic, FrigateCommand.DETECT_DISABLE.value)

    # Motion detection commands

    def enable_motion_detection(self, camera: str) -> bool:
        """
        Enable motion detection on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/motion/set"
        return self._publish_command(topic, FrigateCommand.MOTION_ENABLE.value)

    def disable_motion_detection(self, camera: str) -> bool:
        """
        Disable motion detection on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/motion/set"
        return self._publish_command(topic, FrigateCommand.MOTION_DISABLE.value)

    def improve_contrast(self, camera: str) -> bool:
        """
        Improve motion detection contrast on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/motion_contour_area/set"
        return self._publish_command(topic, FrigateCommand.MOTION_IMPROVE_CONTRAST.value)

    # Audio detection commands

    def enable_audio_detection(self, camera: str) -> bool:
        """
        Enable audio detection on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/audio/set"
        return self._publish_command(topic, FrigateCommand.AUDIO_ENABLE.value)

    def disable_audio_detection(self, camera: str) -> bool:
        """
        Disable audio detection on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/audio/set"
        return self._publish_command(topic, FrigateCommand.AUDIO_DISABLE.value)

    # PTZ commands

    def ptz_move(self, camera: str, action: str) -> bool:
        """
        Send PTZ movement command.

        Args:
            camera: Camera name
            action: PTZ action (e.g., 'MOVE_UP', 'MOVE_DOWN', 'ZOOM_IN', etc.)

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/ptz"
        return self._publish_command(topic, action)

    def enable_ptz_autotrack(self, camera: str) -> bool:
        """
        Enable PTZ autotracking on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/ptz_autotracker/set"
        return self._publish_command(topic, FrigateCommand.PTZ_AUTOTRACK_ENABLE.value)

    def disable_ptz_autotrack(self, camera: str) -> bool:
        """
        Disable PTZ autotracking on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/ptz_autotracker/set"
        return self._publish_command(topic, FrigateCommand.PTZ_AUTOTRACK_DISABLE.value)

    # Camera enable/disable commands

    def enable_camera(self, camera: str) -> bool:
        """
        Enable a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/enabled/set"
        return self._publish_command(topic, FrigateCommand.CAMERA_ENABLE.value)

    def disable_camera(self, camera: str) -> bool:
        """
        Disable a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/enabled/set"
        return self._publish_command(topic, FrigateCommand.CAMERA_DISABLE.value)

    # Snapshots commands

    def enable_snapshots(self, camera: str) -> bool:
        """
        Enable snapshots on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/snapshots/set"
        return self._publish_command(topic, FrigateCommand.SNAPSHOTS_ENABLE.value)

    def disable_snapshots(self, camera: str) -> bool:
        """
        Disable snapshots on a camera.

        Args:
            camera: Camera name

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/snapshots/set"
        return self._publish_command(topic, FrigateCommand.SNAPSHOTS_DISABLE.value)

    # Motion threshold and contour area commands

    def set_motion_threshold(self, camera: str, threshold: int) -> bool:
        """
        Set motion detection threshold on a camera.

        Args:
            camera: Camera name
            threshold: Motion threshold value

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/motion_threshold/set"
        return self._publish_command(topic, str(threshold))

    def set_motion_contour_area(self, camera: str, area: int) -> bool:
        """
        Set motion contour area on a camera.

        Args:
            camera: Camera name
            area: Contour area value

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/{camera}/motion_contour_area/set"
        return self._publish_command(topic, str(area))

    # Review status commands

    def set_review_status(self, event_id: str, status: str) -> bool:
        """
        Set review status for an event.

        Args:
            event_id: Event ID
            status: Review status (e.g., 'reviewed', 'not_reviewed')

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/review/{event_id}/set"
        return self._publish_command(topic, status)

    # System commands

    def restart_frigate(self) -> bool:
        """
        Restart Frigate service.

        Returns:
            True if command sent successfully
        """
        topic = f"{self.base_topic}/restart"
        return self._publish_command(topic, "")

    # ==================== Query Methods ====================

    def get_cameras(self) -> Dict[str, CameraInfo]:
        """
        Get dictionary of all discovered cameras with their current state.

        Returns:
            Dictionary mapping camera name to CameraInfo object
        """
        return dict(self._cameras)

    def get_camera_names(self) -> List[str]:
        """
        Get list of all discovered camera names.

        Returns:
            List of camera names
        """
        return list(self._cameras.keys())

    def get_base_topic(self) -> str:
        """
        Get the base MQTT topic for Frigate.

        Returns:
            Base topic string (e.g., 'frigate')
        """
        return self.base_topic

    def get_mqtt_host(self) -> str:
        """
        Get the MQTT broker host.

        Returns:
            MQTT host string
        """
        return self.mqtt_host

    def get_mqtt_port(self) -> int:
        """
        Get the MQTT broker port.

        Returns:
            MQTT port number
        """
        return self.mqtt_port
