#!/usr/bin/env python3
"""
Frigate Manager

A comprehensive manager for Frigate NVR that handles:
1. Rich email notifications for camera events
2. General event loop for extensibility

Configuration is managed via a single YAML file.
"""

import argparse
import json
import logging
import os
import re
import signal
import smtplib
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

import yaml

from frigate_mqtt_client import FrigateMQTTClient, FrigateEvent, FrigateEventType


# =============================================================================
# Configuration Data Classes
# =============================================================================

@dataclass
class SmtpConfig:
    """SMTP server configuration."""
    host: str
    port: int
    username: str
    password: str
    use_tls: bool = True
    use_ssl: bool = False
    from_address: str = ""
    from_name: str = "Frigate Alerts"
    timeout: int = 30

    def __post_init__(self):
        if not self.from_address:
            self.from_address = self.username


@dataclass
class MqttConfig:
    """MQTT broker configuration."""
    host: str
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    base_topic: str = "frigate"


@dataclass
class FrigateServerConfig:
    """Frigate server configuration."""
    # Authenticated URL (preferred for API calls, e.g., http://frigate:8971)
    auth_url: Optional[str] = None
    # Unauthenticated URL (fallback, e.g., http://frigate:5000)
    unauth_url: str = "http://frigate:5000"
    # External URL for links in emails (uses auth if available)
    external_url: Optional[str] = None
    # Authentication credentials (for JWT token generation)
    username: Optional[str] = None
    password: Optional[str] = None

    def get_api_url(self) -> str:
        """Get the preferred API URL (authenticated if available, else unauthenticated)."""
        if self.auth_url and self.username and self.password:
            return self.auth_url
        return self.unauth_url

    def get_external_url(self) -> str:
        """Get the external URL, falling back to API URL."""
        return self.external_url or self.get_api_url()

    def needs_auth(self) -> bool:
        """Check if authentication is configured."""
        return bool(self.auth_url and self.username and self.password)


@dataclass
class ConnectivityCheckerConfig:
    """Configuration for camera connectivity checker."""
    exceptions: Dict[str, str] = field(default_factory=dict)


@dataclass
class NotificationRule:
    """Configuration for a single notification rule."""
    camera: str  # Regex pattern for camera name
    object_type: str  # Regex pattern for object type (person, car, dog, etc.)
    email_to: List[str]
    hysteresis_seconds: float = 60.0  # Minimum time between notifications
    min_score: float = 0.5  # Minimum confidence score to notify
    enabled: bool = True
    zones: Optional[List[str]] = None  # Only notify if in these zones (None = all zones)
    notify_on_new: bool = True  # Notify on new events
    notify_on_end: bool = False  # Notify when event ends
    include_thumbnail: bool = True
    include_snapshot: bool = False
    include_urls: bool = True  # Include event and clip URLs in notification
    subject_template: str = "[{camera}] {label} detected"
    quiet_hours_start: Optional[str] = None  # e.g., "22:00"
    quiet_hours_end: Optional[str] = None  # e.g., "07:00"
    # Compiled regex patterns (set during initialization)
    camera_pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False)
    object_type_pattern: Optional[re.Pattern] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        """Compile regex patterns for camera and object_type matching."""
        # Compile patterns with full match (anchored)
        self.camera_pattern = re.compile(f'^{self.camera}$', re.IGNORECASE)
        self.object_type_pattern = re.compile(f'^{self.object_type}$', re.IGNORECASE)

    def is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return False

        now = datetime.now().time()
        start = datetime.strptime(self.quiet_hours_start, "%H:%M").time()
        end = datetime.strptime(self.quiet_hours_end, "%H:%M").time()

        if start <= end:
            return start <= now <= end
        else:
            # Quiet hours span midnight
            return now >= start or now <= end


# =============================================================================
# Configuration Loader
# =============================================================================

class ManagerConfig:
    """Load and validate configuration from YAML file."""

    def __init__(self, config_path: str):
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to YAML configuration file

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(os.path.expandvars(f.read()))

        # Parse SMTP config
        smtp_data = data.get('smtp', {})
        self.smtp = SmtpConfig(
            host=smtp_data.get('host', 'localhost'),
            port=smtp_data.get('port', 587),
            username=smtp_data.get('username', ''),
            password=smtp_data.get('password', ''),
            use_tls=smtp_data.get('use_tls', True),
            use_ssl=smtp_data.get('use_ssl', False),
            from_address=smtp_data.get('from_address', ''),
            from_name=smtp_data.get('from_name', 'Frigate Alerts'),
            timeout=smtp_data.get('timeout', 30),
        )

        # Parse MQTT config
        mqtt_data = data.get('mqtt', {})
        self.mqtt = MqttConfig(
            host=mqtt_data.get('host', 'localhost'),
            port=mqtt_data.get('port', 1883),
            username=mqtt_data.get('username'),
            password=mqtt_data.get('password'),
            base_topic=mqtt_data.get('base_topic', 'frigate'),
        )

        # Parse Frigate server config
        frigate_data = data.get('frigate', {})
        self.frigate = FrigateServerConfig(
            auth_url=frigate_data.get('auth_url'),
            unauth_url=frigate_data.get('unauth_url', 'http://frigate:5000'),
            external_url=frigate_data.get('external_url'),
            username=frigate_data.get('username'),
            password=frigate_data.get('password'),
        )

        # Parse connectivity checker config
        connectivity_data = data.get('connectivity_checker', {})
        self.connectivity_checker = ConnectivityCheckerConfig(
            exceptions=connectivity_data.get('exceptions', {})
        )

        # Parse notification defaults and rules
        notifications = data.get('notifications', {})
        defaults = notifications.get('defaults', {})
        self.notification_rules = []
        for rule_data in notifications.get('rules', []):
            rule = NotificationRule(
                enabled=rule_data.get('enabled',
                                      defaults.get('enabled', True)),
                camera=rule_data.get('camera',
                                     defaults.get('camera', '.*')),
                object_type=rule_data.get('object_type',
                                          defaults.get('object_type', '.*')),
                email_to=rule_data.get('email_to',
                                       defaults.get('email_to', [])),
                hysteresis_seconds=rule_data.get('hysteresis_seconds',
                                                 defaults.get('hysteresis_seconds', 60.0)),
                min_score=rule_data.get('min_score',
                                        defaults.get('min_score', 0.5)),
                zones=rule_data.get('zones',
                                    defaults.get('zones', [])),
                notify_on_new=rule_data.get('notify_on_new',
                                            defaults.get('notify_on_new', True)),
                notify_on_end=rule_data.get('notify_on_end',
                                            defaults.get('notify_on_end', False)),
                include_thumbnail=rule_data.get('include_thumbnail',
                                                defaults.get('include_thumbnail', True)),
                include_snapshot=rule_data.get('include_snapshot',
                                               defaults.get('include_snapshot', False)),
                include_urls=rule_data.get('include_urls',
                                           defaults.get('include_urls', True)),
                subject_template=rule_data.get('subject_template',
                                               defaults.get('subject_template',
                                                            "[{camera}] {label} detected")),
                quiet_hours_start=rule_data.get('quiet_hours_start',
                                                defaults.get('quiet_hours_start', None)),
                quiet_hours_end=rule_data.get('quiet_hours_end',
                                              defaults.get('quiet_hours_end', None)),
            )
            self.notification_rules.append(rule)


# =============================================================================
# Email Sender
# =============================================================================

class EmailSender:
    """Handle sending emails via SMTP."""

    def __init__(self, config: SmtpConfig):
        """
        Initialize email sender.

        Args:
            config: SMTP configuration
        """
        self.config = config
        self._logger = logging.getLogger(f"{__name__}.EmailSender")

    def send_html_email(
        self,
        to_addresses: List[str],
        subject: str,
        html_body: str,
        plain_body: Optional[str] = None,
        embedded_images: Optional[Dict[str, bytes]] = None
    ) -> bool:
        """
        Send an HTML email with optional embedded images.

        Args:
            to_addresses: List of recipient email addresses
            subject: Email subject
            html_body: HTML content of the email
            plain_body: Optional plain text fallback
            embedded_images: Dict mapping Content-ID to image bytes

        Returns:
            True if email sent successfully
        """
        if not to_addresses:
            self._logger.warning("No recipients specified, skipping email")
            return False

        try:
            # Create message
            msg = MIMEMultipart('related')
            # Properly encode subject with unicode support
            msg['Subject'] = Header(subject, 'utf-8').encode()
            msg['From'] = f"{self.config.from_name} <{self.config.from_address}>"
            msg['To'] = ', '.join(to_addresses)

            # Create alternative part for text/html
            msg_alt = MIMEMultipart('alternative')
            msg.attach(msg_alt)

            # Add plain text part with explicit UTF-8 encoding
            if plain_body:
                msg_alt.attach(MIMEText(plain_body, 'plain', 'utf-8'))

            # Add HTML part with explicit UTF-8 encoding
            msg_alt.attach(MIMEText(html_body, 'html', 'utf-8'))

            # Add embedded images
            if embedded_images:
                for cid, image_data in embedded_images.items():
                    img = MIMEImage(image_data)
                    img.add_header('Content-ID', f'<{cid}>')
                    img.add_header('Content-Disposition', 'inline', filename=f'{cid}.jpg')
                    msg.attach(img)

            # Send email
            self._send_message(msg, to_addresses)
            self._logger.info("Email sent successfully to %s", to_addresses)
            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Failed to send email: %s", e)
            return False

    def _send_message(self, msg: MIMEMultipart, to_addresses: List[str]):
        """Send message via SMTP."""
        # Generate message string once before connection
        msg_string = msg.as_string()
        msg_size = len(msg_string)
        self._logger.debug("Sending email of size %d bytes to %s", msg_size, to_addresses)

        try:
            if self.config.use_ssl:
                # SSL connection
                with smtplib.SMTP_SSL(
                    self.config.host,
                    self.config.port,
                    timeout=self.config.timeout
                ) as server:
                    server.ehlo()
                    if self.config.username and self.config.password:
                        server.login(self.config.username, self.config.password)
                    server.sendmail(
                        self.config.from_address,
                        to_addresses,
                        msg_string
                    )
            else:
                # Plain or STARTTLS connection
                with smtplib.SMTP(
                    self.config.host,
                    self.config.port,
                    timeout=self.config.timeout
                ) as server:
                    server.ehlo()
                    if self.config.use_tls:
                        server.starttls()
                        server.ehlo()  # RFC requirement after STARTTLS
                    if self.config.username and self.config.password:
                        server.login(self.config.username, self.config.password)
                    server.sendmail(
                        self.config.from_address,
                        to_addresses,
                        msg_string
                    )
        except socket.timeout:
            self._logger.error("SMTP timeout after %d s (message size: %d bytes)",
                               self.config.timeout, msg_size)
            raise
        except Exception as e:
            self._logger.error("SMTP error: %s: %s", type(e).__name__, str(e))
            raise


# =============================================================================
# Frigate API Helper
# =============================================================================

class FrigateApiHelper:
    """Helper for fetching data from Frigate's HTTP API."""

    def __init__(self, config: FrigateServerConfig):
        """
        Initialize Frigate API helper.

        Args:
            config: Frigate server configuration
        """
        self.config = config
        self._logger = logging.getLogger(f"{__name__}.FrigateApiHelper")
        self._jwt_token: Optional[str] = None
        self._token_expiry: float = 0
        self._token_refresh_sec: float = 8 * 3600.0     # 8 hours
        self._auth_lock = threading.Lock()
        self._login_in_progress = False

        # If authentication is configured, login immediately
        if self.config.needs_auth():
            if not self._login():
                self._logger.warning(
                    "Initial authentication failed, will retry on first API call"
                )

    def get_thumbnail_url(self, event_id: str) -> str:
        """Get thumbnail URL for an event."""
        return f"{self.config.get_api_url()}/api/events/{event_id}/thumbnail.jpg"

    def get_snapshot_url(self, event_id: str) -> str:
        """Get snapshot URL for an event."""
        return f"{self.config.get_api_url()}/api/events/{event_id}/snapshot.jpg"

    def get_clip_url(self, event_id: str) -> str:
        """Get clip URL for an event."""
        return f"{self.config.get_external_url()}/api/events/{event_id}/clip.mp4"

    def get_event_url(self, event_id: str) -> str:
        """Get the web UI URL to view an event."""
        # Use fragment identifier which is more resilient to email client URL mangling
        return f"{self.config.get_external_url()}/review#{event_id}"

    def get_cameras_with_ip(self) -> Dict[str, str]:
        """
        Get dictionary of all discovered cameras with their IP addresses.

        Fetches the full Frigate config and extracts camera IPs from RTSP URLs.

        Returns:
            Dictionary mapping camera name to IP address
        """
        try:
            config_url = f"{self.config.get_api_url()}/api/config"
            req = urllib.request.Request(config_url)

            # Add JWT token as Bearer token if authenticated
            if self.config.needs_auth() and self._jwt_token:
                req.add_header('Authorization', f'Bearer {self._jwt_token}')

            with urllib.request.urlopen(req, timeout=10) as response:
                config_data = json.loads(response.read().decode('utf-8'))
                result = {}

                # Extract cameras from config
                cameras = config_data.get('cameras', {})
                for camera_name, camera_info in cameras.items():
                    ip = self._extract_ip_from_camera(camera_info)
                    if ip:
                        result[camera_name] = ip

                self._logger.debug("Extracted IPs for %d cameras", len(result))
                return result
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Failed to get cameras from config: %s", e)
            return {}

    def _extract_ip_from_camera(self, camera_info: Dict) -> Optional[str]:
        """
        Extract IP address from camera configuration.

        Tries to parse from ffmpeg inputs (which contain RTSP URLs).

        Args:
            camera_info: Camera configuration dictionary from Frigate config

        Returns:
            IP address or hostname if found, None otherwise
        """
        # Try ffmpeg inputs (modern config structure)
        if 'ffmpeg' in camera_info:
            ffmpeg_config = camera_info['ffmpeg']
            # Check inputs array
            if 'inputs' in ffmpeg_config:
                for input_cfg in ffmpeg_config['inputs']:
                    if 'path' in input_cfg:
                        ip = self._extract_ip_from_url(input_cfg['path'])
                        if ip:
                            return ip
        return None

    def _extract_ip_from_url(self, url: str) -> Optional[str]:
        """
        Extract IP address from a URL string.

        Handles rtsp://, http://, and rtp:// URLs.
        """
        # Pattern to match IP address (basic pattern)
        pattern = r'(?:rtsp|http|rtp)://(?:.*@)?([\d.]+|[\w.-]+)(?::|/)'
        match = re.search(pattern, url)
        if match:
            host = match.group(1)
            # Simple check: if it looks like an IP or hostname
            if host and not host.startswith('0.0.0.0'):
                return host
        return None

    def _login(self) -> bool:
        """Login to Frigate and obtain JWT token."""
        if not self.config.needs_auth():
            return True

        # Prevent multiple simultaneous login attempts
        with self._auth_lock:
            # Check if another thread already refreshed the token
            if self._jwt_token and time.time() < self._token_expiry:
                return True

            if self._login_in_progress:
                self._logger.debug("Login already in progress, waiting...")
                return False

            self._login_in_progress = True

        try:
            login_url = f"{self.config.auth_url}/api/login"
            data = {
                'user': self.config.username,
                'password': self.config.password
            }

            # Convert data to JSON and encode
            json_data = json.dumps(data).encode('utf-8')

            req = urllib.request.Request(
                login_url,
                data=json_data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                # Extract token from Set-Cookie header
                cookies = response.getheader('Set-Cookie')
                if cookies:
                    # Parse frigate_token from cookies
                    for cookie in cookies.split(';'):
                        if 'frigate_token=' in cookie:
                            token = cookie.split('frigate_token=')[1].split(';')[0]
                            if not token or len(token) < 10:
                                self._logger.error("Invalid token received from Frigate")
                                return False

                            with self._auth_lock:
                                self._jwt_token = token
                                # Tokens expire after 24 hours by default
                                self._token_expiry = time.time() + self._token_refresh_sec
                                self._login_in_progress = False

                            self._logger.info("Successfully authenticated with Frigate")
                            return True

                self._logger.error("No token found in login response")
                return False

        except urllib.error.HTTPError as e:
            self._logger.error("Login failed with HTTP %d: %s", e.code, e.reason)
            return False
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Login error: %s", e)
            return False
        finally:
            with self._auth_lock:
                self._login_in_progress = False

    def _ensure_authenticated(self) -> bool:
        """Ensure we have a valid JWT token, refreshing if needed."""
        if not self.config.needs_auth():
            return True

        current_time = time.time()

        # Check if token needs refresh (add 60 second buffer before actual expiry)
        if not self._jwt_token or current_time >= (self._token_expiry - 60):
            if not self._jwt_token:
                self._logger.info("No token available, logging in...")
            else:
                time_until_expiry = self._token_expiry - current_time
                self._logger.info("Token expires in %.1f seconds, refreshing...", time_until_expiry)
            return self._login()

        return True

    def fetch_thumbnail(self, event_id: str, timeout: float = 10.0) -> Optional[bytes]:
        """
        Fetch thumbnail image for an event.

        Args:
            event_id: Frigate event ID
            timeout: Request timeout in seconds

        Returns:
            Image bytes or None if failed
        """
        url = self.get_thumbnail_url(event_id)
        return self._fetch_image(url, timeout)

    def fetch_snapshot(self, event_id: str, timeout: float = 10.0) -> Optional[bytes]:
        """
        Fetch snapshot image for an event.

        Args:
            event_id: Frigate event ID
            timeout: Request timeout in seconds

        Returns:
            Image bytes or None if failed
        """
        url = self.get_snapshot_url(event_id)
        return self._fetch_image(url, timeout)

    def _fetch_image(self, url: str, timeout: float, _retry_count: int = 0) -> Optional[bytes]:
        """Fetch image from URL with JWT token authentication."""
        # Prevent infinite recursion
        if _retry_count > 1:
            self._logger.error("Maximum retry attempts reached for %s", url)
            return None

        # Ensure we have a valid token
        if not self._ensure_authenticated():
            self._logger.error("Authentication failed, cannot fetch image")
            return None

        try:
            req = urllib.request.Request(url)

            # Add JWT token as Bearer token if authenticated
            if self.config.needs_auth() and self._jwt_token:
                req.add_header('Authorization', f'Bearer {self._jwt_token}')

            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            self._logger.warning("Failed to fetch image from %s: HTTP %d", url, e.code)
            # If we get a 401, try re-authenticating once
            if e.code == 401 and _retry_count == 0:
                self._logger.info("Got 401, attempting to re-authenticate...")
                # Force token refresh by clearing current token
                with self._auth_lock:
                    self._jwt_token = None
                    self._token_expiry = 0

                if self._login():
                    # Retry the request with new token
                    return self._fetch_image(url, timeout, _retry_count=_retry_count + 1)
            return None
        except urllib.error.URLError as e:
            self._logger.warning("Failed to fetch image from %s: %s", url, e)
            return None
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Error fetching image: %s", e)
            return None


# =============================================================================
# Notification Manager
# =============================================================================

class HysteresisTracker:
    """Track notification hysteresis to prevent notification spam."""

    def __init__(self):
        self._last_notification: Dict[str, float] = {}  # type: ignore
        self._lock = threading.Lock()

    def get_key(self, camera: str, object_type: str) -> str:
        """Generate a unique key for camera/object_type combination."""
        return f"{camera}:{object_type}"

    def can_notify(self, camera: str, object_type: str, hysteresis_seconds: float) -> bool:
        """
        Check if enough time has passed since last notification.

        Args:
            camera: Camera name
            object_type: Type of detected object
            hysteresis_seconds: Minimum seconds between notifications

        Returns:
            True if notification is allowed
        """
        key = self.get_key(camera, object_type)
        current_time = time.time()

        with self._lock:
            last_time = self._last_notification.get(key, 0)
            if current_time - last_time >= hysteresis_seconds:
                return True
            return False

    def record_notification(self, camera: str, object_type: str):
        """Record that a notification was sent."""
        key = self.get_key(camera, object_type)
        with self._lock:
            self._last_notification[key] = time.time()

    def clear(self):
        """Clear all hysteresis tracking."""
        with self._lock:
            self._last_notification.clear()


class NotificationManager:
    """
    Manage notifications for Frigate events.

    Handles:
    - Matching events to notification rules
    - Rate limiting via hysteresis
    - Email composition and sending
    - Thumbnail embedding
    """

    def __init__(self, config: ManagerConfig):
        """
        Initialize notification manager.

        Args:
            config: Notification configuration
        """
        self.config = config
        self._logger = logging.getLogger(f"{__name__}.NotificationManager")

        # Initialize components
        self.email_sender = EmailSender(config.smtp)
        self.frigate_api = FrigateApiHelper(config.frigate)
        self.hysteresis = HysteresisTracker()

        # All rules stored in a single list - regex matching doesn't benefit from indexing
        self._rules: List[NotificationRule] = config.notification_rules

    def get_matching_rules(self, event: FrigateEvent) -> List[NotificationRule]:
        """
        Get all rules that match an event.

        Args:
            event: Frigate event

        Returns:
            List of matching rules
        """
        camera = event.after.camera
        label = event.after.label
        zones = set(event.after.current_zones)

        matching = []

        # Check all rules using regex matching
        for rule in self._rules:
            if self._rule_matches(rule, camera, label, zones):
                matching.append(rule)

        return matching

    def _rule_matches(
        self,
        rule: NotificationRule,
        camera: str,
        label: str,
        zones: Set[str]
    ) -> bool:
        """Check if a rule matches the given camera, label and zones."""
        if not rule.enabled:
            return False

        # Check camera name using regex pattern
        if rule.camera_pattern is not None:
            if not rule.camera_pattern.match(camera):
                return False

        # Check object type using regex pattern
        if rule.object_type_pattern is not None:
            if not rule.object_type_pattern.match(label):
                return False

        # Check zones
        if rule.zones:
            if not zones.intersection(rule.zones):
                return False

        return True

    def process_event(self, event: FrigateEvent):
        """
        Process a Frigate event and send notifications if appropriate.

        Args:
            event: Frigate event
        """
        # Determine if we should notify based on event type
        is_new = event.event_type == FrigateEventType.NEW
        is_end = event.event_type == FrigateEventType.END

        # Get matching rules
        matching_rules = self.get_matching_rules(event)

        if not matching_rules:
            self._logger.debug(
                "No matching rules for event: camera=%s, label=%s",
                event.after.camera, event.after.label
            )
            return

        # Process each matching rule
        for rule in matching_rules:
            self._process_rule(event, rule, is_new, is_end)

    def _process_rule(
        self,
        event: FrigateEvent,
        rule: NotificationRule,
        is_new: bool,
        is_end: bool
    ):
        """Process a single rule for an event."""
        camera = event.after.camera
        label = event.after.label
        score = event.after.top_score

        # Check if we should notify for this event type
        if is_new and not rule.notify_on_new:
            return
        if is_end and not rule.notify_on_end:
            return
        if not is_new and not is_end:
            # UPDATE event - skip unless we want to add update notifications later
            return

        # Check minimum score
        if score < rule.min_score:
            self._logger.debug(
                "Score %.2f below threshold %.2f for %s on %s",
                score, rule.min_score, label, camera
            )
            return

        # Check quiet hours
        if rule.is_quiet_hours():
            self._logger.debug("Quiet hours active, skipping notification")
            return

        # Check hysteresis
        if not self.hysteresis.can_notify(camera, label, rule.hysteresis_seconds):
            self._logger.debug(
                "Hysteresis active for %s on %s (%.0fs)",
                label, camera, rule.hysteresis_seconds
            )
            return

        # Send notification
        success = self._send_notification(event, rule)

        if success:
            self.hysteresis.record_notification(camera, label)

    def _send_notification(self, event: FrigateEvent, rule: NotificationRule) -> bool:
        """Send notification email for an event."""
        event_data = event.after
        event_id = event_data.id

        # Build subject
        subject = rule.subject_template.format(
            camera=event_data.camera,
            label=event_data.label,
            score=f"{event_data.top_score:.0%}",
            zones=', '.join(event_data.current_zones) or 'none',
        )

        # Fetch images
        embedded_images = {}
        thumbnail_cid = None
        snapshot_cid = None

        if rule.include_thumbnail:
            thumbnail_data = self.frigate_api.fetch_thumbnail(event_id)
            if thumbnail_data:
                thumbnail_cid = f"thumbnail_{event_id}"
                embedded_images[thumbnail_cid] = thumbnail_data

        if rule.include_snapshot:
            snapshot_data = self.frigate_api.fetch_snapshot(event_id)
            if snapshot_data:
                snapshot_cid = f"snapshot_{event_id}"
                embedded_images[snapshot_cid] = snapshot_data

        # Build email body
        html_body = self._build_html_body(
            event,
            thumbnail_cid=thumbnail_cid,
            snapshot_cid=snapshot_cid,
            include_urls=rule.include_urls
        )

        plain_body = self._build_plain_body(event, include_urls=rule.include_urls)

        # Send email
        return self.email_sender.send_html_email(
            to_addresses=rule.email_to,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
            embedded_images=embedded_images if embedded_images else None
        )

    def _build_html_body(
        self,
        event: FrigateEvent,
        thumbnail_cid: Optional[str] = None,
        snapshot_cid: Optional[str] = None,
        include_urls: bool = True
    ) -> str:
        """Build HTML email body."""
        event_data = event.after
        event_url = self.frigate_api.get_event_url(event_data.id)
        clip_url = self.frigate_api.get_clip_url(event_data.id)

        # Format timestamp
        timestamp = datetime.fromtimestamp(event_data.start_time)
        timestamp_str = timestamp.strftime("%Y-%m-%d %I:%M:%S %p")

        # Build zones string
        zones_str = (
            ', '.join(event_data.current_zones) if event_data.current_zones else 'None'
        )
        entered_zones_str = (
            ', '.join(event_data.entered_zones) if event_data.entered_zones else 'None'
        )

        # Build attributes string
        attrs_str = ''
        if event_data.attributes:
            attrs_list = [f"{k}: {v:.0%}" for k, v in event_data.attributes.items()]
            attrs_str = ', '.join(attrs_list)

        # Sub-label info
        sub_label_str = ''
        if event_data.sub_label:
            sub_label_str = f"{event_data.sub_label[0]} ({event_data.sub_label[1]:.0%})"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: #2563eb;
            color: white;
            padding: 20px;
            border-radius: 8px 8px 0 0;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
        }}
        .content {{
            background: #f8fafc;
            padding: 20px;
            border: 1px solid #e2e8f0;
        }}
        .image-container {{
            text-align: center;
            margin: 20px 0;
        }}
        .image-container img {{
            max-width: 100%;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .details {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            margin: 15px 0;
        }}
        .detail-row {{
            display: flex;
            padding: 8px 0;
            border-bottom: 1px solid #e2e8f0;
        }}
        .detail-row:last-child {{
            border-bottom: none;
        }}
        .detail-label {{
            font-weight: 600;
            width: 140px;
            color: #64748b;
        }}
        .detail-value {{
            flex: 1;
        }}
        .button {{
            display: inline-block;
            background: #2563eb;
            color: white;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 6px;
            margin: 10px 0;
        }}
        .footer {{
            background: #f1f5f9;
            padding: 15px 20px;
            border-radius: 0 0 8px 8px;
            border: 1px solid #e2e8f0;
            border-top: none;
            font-size: 12px;
            color: #64748b;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎥 {event_data.label.title()} Detected</h1>
    </div>
    <div class="content">
"""

        # Add thumbnail
        if thumbnail_cid:
            html += f"""
        <div class="image-container">
            <img src="cid:{thumbnail_cid}" alt="Detection thumbnail">
        </div>
"""

        # Add snapshot if different from thumbnail
        if snapshot_cid:
            html += f"""
        <div class="image-container">
            <img src="cid:{snapshot_cid}" alt="Detection snapshot">
        </div>
"""

        html += f"""
        <div class="details">
            <div class="detail-row">
                <span class="detail-label">Camera</span>
                <span class="detail-value">{event_data.camera}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Object</span>
                <span class="detail-value">{event_data.label}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Confidence</span>
                <span class="detail-value">{event_data.top_score:.0%}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Time</span>
                <span class="detail-value">{timestamp_str}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Current Zones</span>
                <span class="detail-value">{zones_str}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Entered Zones</span>
                <span class="detail-value">{entered_zones_str}</span>
            </div>
"""

        if sub_label_str:
            html += f"""
            <div class="detail-row">
                <span class="detail-label">Identified As</span>
                <span class="detail-value">{sub_label_str}</span>
            </div>
"""

        if attrs_str:
            html += f"""
            <div class="detail-row">
                <span class="detail-label">Attributes</span>
                <span class="detail-value">{attrs_str}</span>
            </div>
"""

        html += """
        </div>
"""

        if include_urls:
            html += f"""
        <div style="text-align: center;">
            <a href="{event_url}" class="button">📋 View Review Page</a>
            <a href="{clip_url}" class="button">🎬 View Video Clip</a>
        </div>
"""

        html += """
    </div>
</body>
</html>
"""
        return html

    def _build_plain_body(self, event: FrigateEvent, include_urls: bool = True) -> str:
        """Build plain text email body."""
        event_data = event.after
        event_url = self.frigate_api.get_event_url(event_data.id)
        clip_url = self.frigate_api.get_clip_url(event_data.id)

        timestamp = datetime.fromtimestamp(event_data.start_time)
        timestamp_str = timestamp.strftime("%Y-%m-%d %I:%M:%S %p")

        zones_str = ', '.join(event_data.current_zones) if event_data.current_zones else 'None'

        text = f"""
Details:
- Camera: {event_data.camera}
- Object: {event_data.label}
- Confidence: {event_data.top_score:.0%}
- Time: {timestamp_str}
- Zones: {zones_str}
"""

        if include_urls:
            text += f"""

Review Page: {event_url}
Video Clip: {clip_url}
"""

        return text.strip()


# =============================================================================
# Event Handler Base Class
# =============================================================================

class EventHandler(ABC):
    """Abstract base class for event handlers."""

    @abstractmethod
    def handle_event(self, event: FrigateEvent):
        """Handle a Frigate event."""
        pass    # pylint: disable=unnecessary-pass

    @abstractmethod
    def start(self):
        """Start the handler."""
        pass    # pylint: disable=unnecessary-pass

    @abstractmethod
    def stop(self):
        """Stop the handler."""
        pass    # pylint: disable=unnecessary-pass


# =============================================================================
# General Event Loop (Stub)
# =============================================================================

class EventLoop:
    """
    General event loop for Frigate Manager.

    Provides a framework for handling Frigate events with pluggable handlers.
    Currently stubbed - extend with additional handlers as needed.
    """

    def __init__(self, config: ManagerConfig, mqtt_client: FrigateMQTTClient):
        """
        Initialize event loop.

        Args:
            config: Notification configuration
            mqtt_client: MQTT client instance
        """
        self.config = config
        self._logger = logging.getLogger(f"{__name__}.EventLoop")

        self._mqtt_client = mqtt_client
        self._handlers: List[EventHandler] = []
        self._event_callbacks: List[Callable[[FrigateEvent], None]] = []
        self._running = False
        self._stop_event = threading.Event()

    def add_handler(self, handler: EventHandler):
        """Add an event handler."""
        self._handlers.append(handler)

    def add_callback(self, callback: Callable[[FrigateEvent], None]):
        """Add a simple callback for events."""
        self._event_callbacks.append(callback)

    def start(self) -> bool:
        """
        Start the event loop.

        Returns:
            True if started successfully
        """
        self._logger.info("Starting event loop...")

        # Connect to MQTT
        if not self._mqtt_client.connect():
            self._logger.error("Failed to connect to MQTT broker")
            return False

        # Register event handler
        self._mqtt_client.on_event(self._on_event)

        # Start all handlers
        for handler in self._handlers:
            handler.start()

        self._running = True
        self._logger.info("Event loop started")
        return True

    def stop(self):
        """Stop the event loop."""
        self._logger.info("Stopping event loop...")
        self._running = False
        self._stop_event.set()

        # Stop all handlers
        for handler in self._handlers:
            handler.stop()

        # Disconnect MQTT
        if self._mqtt_client:
            self._mqtt_client.disconnect()

        self._logger.info("Event loop stopped")

    def run_forever(self):
        """Run the event loop until stopped."""
        self._logger.info("Running event loop forever (Ctrl+C to stop)...")
        try:
            while self._running:
                self._stop_event.wait(timeout=1.0)
        except KeyboardInterrupt:
            self._logger.info("Received keyboard interrupt")
        finally:
            self.stop()

    def _on_event(self, event: FrigateEvent):
        """Handle incoming Frigate event."""
        self._logger.debug(
            "Received event: type=%s, camera=%s, label=%s",
            event.event_type.value, event.after.camera, event.after.label
        )

        # Dispatch to handlers
        for handler in self._handlers:
            try:
                handler.handle_event(event)
            except Exception as e:  # pylint: disable=broad-exception-caught
                self._logger.error("Handler error: %s", e)

        # Dispatch to callbacks
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:  # pylint: disable=broad-exception-caught
                self._logger.error("Callback error: %s", e)


# =============================================================================
# Notification Handler (wraps NotificationManager as EventHandler)
# =============================================================================

class NotificationHandler(EventHandler):
    """Event handler that sends notifications."""

    def __init__(self, manager: NotificationManager):
        self.manager = manager
        self._logger = logging.getLogger(f"{__name__}.NotificationHandler")

    def handle_event(self, event: FrigateEvent):
        """Handle event by processing through notification manager."""
        self.manager.process_event(event)

    def start(self):
        """Start handler (no-op for notifications)."""
        self._logger.info("Notification handler started")

    def stop(self):
        """Stop handler (no-op for notifications)."""
        self._logger.info("Notification handler stopped")


# =============================================================================
# Camera Connectivity Handler
# =============================================================================

class CameraConnectivityHandler(EventHandler):
    """
    One-shot event handler that checks camera connectivity.

    On first event:
    - Fetches all cameras from Frigate API
    - Checks connectivity to each camera via nc -z <ip> 554
    - Enables/disables cameras via MQTT based on connectivity
    - Applies exceptions (cameras that should always be enabled/disabled)
    """

    def __init__(self, frigate_api: FrigateApiHelper, mqtt_client: Optional[object] = None,
                 exceptions: Optional[Dict[str, str]] = None):
        """
        Initialize connectivity handler.

        Args:
            frigate_api: FrigateApiHelper instance
            mqtt_client: Optional MQTT client for enable/disable commands
            exceptions: Dict of camera names to state ('enabled' or 'disabled')
        """
        self.frigate_api = frigate_api
        self.mqtt_client = mqtt_client
        self.exceptions = exceptions or {}
        self._logger = logging.getLogger(f"{__name__}.CameraConnectivityHandler")

    def handle_event(self, event: FrigateEvent):
        """NOP"""
        pass    # pylint: disable=unnecessary-pass

    def _check_connectivity(self):
        """Check connectivity for all cameras and update their state."""
        self._logger.info("Starting camera connectivity check...")

        try:
            # Get all cameras with their IP addresses
            cameras = self.frigate_api.get_cameras_with_ip()
            if not cameras:
                self._logger.warning("No cameras found or unable to retrieve camera list")
                return

            self._logger.debug("Found %d cameras to check", len(cameras))

            # First, apply exceptions unconditionally
            if self.exceptions:
                self._logger.info("Applying %d camera exceptions", len(self.exceptions))
                for camera_name, desired_state in self.exceptions.items():
                    if desired_state.lower() == 'enabled':
                        self._update_camera_state(camera_name, True, is_exception=True)
                    elif desired_state.lower() == 'disabled':
                        self._update_camera_state(camera_name, False, is_exception=True)
                    else:
                        self._logger.warning(
                            "Invalid state '%s' for camera %s (expected 'enabled' or 'disabled')",
                            desired_state, camera_name
                        )

            # Check connectivity for remaining cameras (not in exceptions)
            cameras_to_check = {
                name: ip for name, ip in cameras.items()
                if name not in self.exceptions
            }

            if cameras_to_check:
                self._logger.info("Checking connectivity for %d cameras", len(cameras_to_check))
                for camera_name, ip_addr in cameras_to_check.items():
                    is_online = self._check_port(ip_addr, 554)
                    self._update_camera_state(camera_name, is_online)

            self._logger.info("Camera connectivity check complete")

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Error during connectivity check: %s", e)

    def _check_port(self, ip_addr: str, port: int, timeout: int = 1) -> bool:
        """
        Check if a port is open on a host using nc.

        Args:
            ip_addr: IP address or hostname
            port: Port number to check
            timeout: Timeout in seconds

        Returns:
            True if port is open (online), False otherwise
        """
        try:
            result = subprocess.run(
                ['nc', '-z', '-w', str(timeout), ip_addr, str(port)],
                capture_output=True,
                timeout=timeout+1,
                check=False
            )
            return result.returncode == 0
        except FileNotFoundError:
            self._logger.error("nc (netcat) command not found. Install netcat-openbsd.")
            return False
        except subprocess.TimeoutExpired:
            self._logger.debug("Connection check to %s:%d timed out", ip_addr, port)
            return False
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.debug("Error checking %s:%d: %s", ip_addr, port, e)
            return False

    def _update_camera_state(self, camera_name: str, is_online: bool, is_exception: bool = False):
        """
        Update camera state via MQTT.

        Args:
            camera_name: Name of the camera
            is_online: Whether the camera is online (or desired state for exceptions)
            is_exception: Whether this is an exception (always enabled/disabled)
        """
        if not self.mqtt_client:
            self._logger.warning("MQTT client not available, cannot update camera state")
            return

        try:
            if is_online:
                success = self.mqtt_client.enable_camera(camera_name)  # type: ignore
                action = "enabled"
            else:
                success = self.mqtt_client.disable_camera(camera_name)  # type: ignore
                action = "disabled"

            status = "successfully" if success else "failed to"
            reason = "(exception)" if is_exception else f"(online: {is_online})"
            self._logger.info(
                "Camera %s %s %s %s",
                camera_name, status, action, reason
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logger.error("Error updating state for camera %s: %s", camera_name, e)

    def start(self):
        """Start handler (no-op, runs on first event)."""
        self._logger.info("Camera connectivity handler started")
        self._check_connectivity()

    def stop(self):
        """Stop handler."""
        self._logger.info("Camera connectivity handler stopped")


# =============================================================================
# Frigate Manager Main Class
# =============================================================================

class FrigateManager:
    """
    Main Frigate Manager class.

    Orchestrates:
    - Configuration loading
    - Notification management
    - Event loop management
    """

    def __init__(self, config_path: str):
        """
        Initialize Frigate Manager.

        Args:
            config_path: Path to YAML configuration file
        """
        self._logger = logging.getLogger(f"{__name__}.FrigateManager")
        self._logger.info("Loading configuration from %s", config_path)

        # Load configuration
        self.config = ManagerConfig(config_path)

        # Initialize MQTT client
        mqtt_client = FrigateMQTTClient(
            mqtt_host=self.config.mqtt.host,
            mqtt_port=self.config.mqtt.port,
            mqtt_username=self.config.mqtt.username,
            mqtt_password=self.config.mqtt.password,
            base_topic=self.config.mqtt.base_topic,
        )

        # Initialize components
        self.notification_manager = NotificationManager(self.config)
        self.event_loop = EventLoop(self.config, mqtt_client)

        # Add notification handler to event loop
        notification_handler = NotificationHandler(self.notification_manager)
        self.event_loop.add_handler(notification_handler)

        # Add camera connectivity handler to event loop
        connectivity_handler = CameraConnectivityHandler(
            self.notification_manager.frigate_api,
            mqtt_client=mqtt_client,
            exceptions=self.config.connectivity_checker.exceptions
        )
        self.event_loop.add_handler(connectivity_handler)

        # Signal handling
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):  # pylint: disable=unused-argument
        """Handle shutdown signals."""
        self._logger.info("Received signal %d, shutting down...", signum)
        self.stop()

    def start(self) -> bool:
        """
        Start Frigate Manager.

        Returns:
            True if started successfully
        """
        self._logger.info("Starting Frigate Manager...")
        return self.event_loop.start()

    def stop(self):
        """Stop Frigate Manager."""
        self._logger.info("Stopping Frigate Manager...")
        self.event_loop.stop()

    def run_forever(self):
        """Run Frigate Manager until stopped."""
        if self.start():
            self.event_loop.run_forever()
        else:
            self._logger.error("Failed to start Frigate Manager")
            sys.exit(1)


# =============================================================================
# CLI Entry Point
# =============================================================================

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
        description='Frigate Manager - Notification and event management for Frigate NVR'
    )
    parser.add_argument(
        '-c', '--config',
        default='frigate-mgr.yml',
        help='Path to configuration file (default: frigate-mgr.yml)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    try:
        # Run the manager
        manager = FrigateManager(args.config)
        manager.run_forever()
    except FileNotFoundError as e:
        logger.error("Configuration file not found: %s", e)
        sys.exit(1)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Fatal error: %s", e)
        sys.exit(1)


if __name__ == '__main__':
    main()
