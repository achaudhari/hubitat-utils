#!/usr/bin/env python3
"""
Frigate MQTT Client CLI

A command-line interface for testing and interacting with Frigate NVR via MQTT.
"""

import argparse
import logging
import sys
import time
from typing import Dict

from frigate_mqtt_client import FrigateMQTTClient, FrigateEvent


class FrigateCLI:
    """Command-line interface for Frigate MQTT client."""

    def __init__(self, client: FrigateMQTTClient):
        self.client = client
        self.running = False

    def setup_event_handlers(self):
        """Set up event handlers for monitoring."""

        def on_event(event: FrigateEvent):
            print(f"\n[EVENT] {event.event_type.value.upper()}")
            print(f"  Camera: {event.after.camera}")
            print(f"  Label: {event.after.label}")
            if event.after.sub_label:
                print(f"  Sub-label: {event.after.sub_label[0]} ({event.after.sub_label[1]:.2f})")
            print(f"  Score: {event.after.score:.2f}")
            print(f"  Top Score: {event.after.top_score:.2f}")
            print(f"  ID: {event.after.id}")
            zones = ', '.join(event.after.current_zones) if event.after.current_zones else 'None'
            print(f"  Zones: {zones}")
            print(f"  Active: {event.after.active}")
            print(f"  Stationary: {event.after.stationary}")
            if event.after.has_snapshot:
                print("  Has Snapshot: Yes")
            if event.after.has_clip:
                print("  Has Clip: Yes")
            if event.after.recognized_license_plate:
                print(f"  License Plate: {event.after.recognized_license_plate} "
                      f"({event.after.recognized_license_plate_score:.2f})")
            if event.after.current_estimated_speed:
                print(f"  Speed: {event.after.current_estimated_speed:.1f}")
            if event.after.attributes:
                attrs = ', '.join([f"{k}: {v:.2f}" for k, v in event.after.attributes.items()])
                print(f"  Attributes: {attrs}")

        def on_availability(available: bool):
            status = "ONLINE" if available else "OFFLINE"
            print(f"\n[AVAILABILITY] Frigate is {status}")

        def on_stats(stats_data: Dict):
            print(f"\n[STATS] Updated at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            if 'cameras' in stats_data:
                for camera, cam_stats in stats_data['cameras'].items():
                    print(f"  {camera}:")
                    print(f"    FPS: {cam_stats.get('camera_fps', 'N/A')}")
                    print(f"    Detection FPS: {cam_stats.get('detection_fps', 'N/A')}")
                    print(f"    Process FPS: {cam_stats.get('process_fps', 'N/A')}")

        def on_detection_state(camera: str, state: str):
            print(f"\n[DETECTION] Camera '{camera}' detection: {state}")

        def on_motion_state(camera: str, state: str):
            print(f"\n[MOTION] Camera '{camera}' motion: {state}")

        def on_audio_state(camera: str, state: str):
            print(f"\n[AUDIO] Camera '{camera}' audio: {state}")

        def on_enabled_state(camera: str, state: str):
            print(f"\n[ENABLED] Camera '{camera}' enabled: {state}")

        def on_recordings_state(camera: str, state: str):
            print(f"\n[RECORDINGS] Camera '{camera}' recordings: {state}")

        def on_snapshots_state(camera: str, state: str):
            print(f"\n[SNAPSHOTS] Camera '{camera}' snapshots: {state}")

        def on_motion_threshold_state(camera: str, state: str):
            print(f"\n[MOTION_THRESHOLD] Camera '{camera}' motion threshold: {state}")

        def on_motion_contour_area_state(camera: str, state: str):
            print(f"\n[MOTION_CONTOUR_AREA] Camera '{camera}' motion contour area: {state}")

        self.client.on_event(on_event)
        self.client.on_availability_change(on_availability)
        self.client.on_stats_update(on_stats)
        self.client.on_detection_state_change(on_detection_state)
        self.client.on_motion_state_change(on_motion_state)
        self.client.on_audio_state_change(on_audio_state)
        self.client.on_enabled_state_change(on_enabled_state)
        self.client.on_recordings_state_change(on_recordings_state)
        self.client.on_snapshots_state_change(on_snapshots_state)
        self.client.on_motion_threshold_state_change(on_motion_threshold_state)
        self.client.on_motion_contour_area_state_change(on_motion_contour_area_state)

    def run_monitor(self, duration: int = 0):
        """
        Run in monitor mode to watch events.

        Args:
            duration: Duration to monitor in seconds (0 = infinite)
        """
        print("Monitoring Frigate events... (Press Ctrl+C to stop)")
        self.setup_event_handlers()

        try:
            if duration > 0:
                time.sleep(duration)
            else:
                while True:
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping monitor...")

    def run_command(self, args):
        """Execute a command based on CLI arguments."""
        camera = args.camera
        command = args.command

        result = False

        # Recording commands
        if command == 'enable-recording':
            result = self.client.enable_recording(camera)
        elif command == 'disable-recording':
            result = self.client.disable_recording(camera)

        # Detection commands
        elif command == 'enable-detection':
            result = self.client.enable_detection(camera)
        elif command == 'disable-detection':
            result = self.client.disable_detection(camera)

        # Motion detection commands
        elif command == 'enable-motion':
            result = self.client.enable_motion_detection(camera)
        elif command == 'disable-motion':
            result = self.client.disable_motion_detection(camera)
        elif command == 'improve-contrast':
            result = self.client.improve_contrast(camera)

        # Audio detection commands
        elif command == 'enable-audio':
            result = self.client.enable_audio_detection(camera)
        elif command == 'disable-audio':
            result = self.client.disable_audio_detection(camera)

        # Camera enable/disable commands
        elif command == 'enable-camera':
            result = self.client.enable_camera(camera)
        elif command == 'disable-camera':
            result = self.client.disable_camera(camera)

        # Snapshot enable/disable commands
        elif command == 'enable-snapshots':
            result = self.client.enable_snapshots(camera)
        elif command == 'disable-snapshots':
            result = self.client.disable_snapshots(camera)

        # Motion threshold and contour area commands
        elif command == 'set-motion-threshold':
            if not hasattr(args, 'value') or args.value is None:
                print("Error: --value is required for set-motion-threshold")
                return False
            result = self.client.set_motion_threshold(camera, int(args.value))
        elif command == 'set-motion-contour-area':
            if not hasattr(args, 'value') or args.value is None:
                print("Error: --value is required for set-motion-contour-area")
                return False
            result = self.client.set_motion_contour_area(camera, int(args.value))

        # Review status command
        elif command == 'set-review-status':
            if not hasattr(args, 'event_id') or args.event_id is None:
                print("Error: --event-id is required for set-review-status")
                return False
            if not hasattr(args, 'status') or args.status is None:
                print("Error: --status is required for set-review-status")
                return False
            result = self.client.set_review_status(args.event_id, args.status)

        # PTZ commands
        elif command.startswith('ptz-'):
            action = command[4:].upper().replace('-', '_')
            result = self.client.ptz_move(camera, action)
        elif command == 'enable-ptz-autotrack':
            result = self.client.enable_ptz_autotrack(camera)
        elif command == 'disable-ptz-autotrack':
            result = self.client.disable_ptz_autotrack(camera)

        # System commands
        elif command == 'restart':
            result = self.client.restart_frigate()

        else:
            print(f"Unknown command: {command}")
            return False

        if result:
            print(f"Command '{command}' sent successfully")
        else:
            print(f"Failed to send command '{command}'")

        return result


def main():
    """main()"""
    parser = argparse.ArgumentParser(
        description='Frigate MQTT Client CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Monitor all events
  %(prog)s --host 192.168.1.100 monitor

  # Monitor for 60 seconds
  %(prog)s --host 192.168.1.100 monitor --duration 60

  # List all cameras
  %(prog)s --host 192.168.1.100 list-cameras

  # List cameras with longer discovery wait time
  %(prog)s --host 192.168.1.100 list-cameras --wait 5

  # Enable detection on a camera
  %(prog)s --host 192.168.1.100 command --camera front_door --command enable-detection

  # Take a snapshot
  %(prog)s --host 192.168.1.100 command --camera front_door --command take-snapshot

  # Enable recording
  %(prog)s --host 192.168.1.100 command --camera front_door --command enable-recording

  # PTZ movement
  %(prog)s --host 192.168.1.100 command --camera front_door --command ptz-move-up

  # Restart Frigate
  %(prog)s --host 192.168.1.100 command --command restart

Available Commands:
  Camera:
    enable-camera, disable-camera

  Recording:
    enable-recording, disable-recording

  Detection:
    enable-detection, disable-detection

  Snapshot:
    take-snapshot

  Snapshots (Enable/Disable):
    enable-snapshots, disable-snapshots

  Motion:
    enable-motion, disable-motion, improve-contrast
    set-motion-threshold --value <threshold>
    set-motion-contour-area --value <area>

  Audio:
    enable-audio, disable-audio

  PTZ:
    ptz-move-up, ptz-move-down, ptz-move-left, ptz-move-right
    ptz-zoom-in, ptz-zoom-out, ptz-stop
    enable-ptz-autotrack, disable-ptz-autotrack

  Review:
    set-review-status --event-id <id> --status <status>

  System:
    restart
        '''
    )

    # Connection arguments
    parser.add_argument('--host', required=True,
                        help='MQTT broker hostname/IP')
    parser.add_argument('--port', type=int, default=1883,
                        help='MQTT broker port (default: 1883)')
    parser.add_argument('--username',
                        help='MQTT username')
    parser.add_argument('--password',
                        help='MQTT password')
    parser.add_argument('--base-topic', default='frigate',
                        help='Base MQTT topic (default: frigate)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')

    # Subcommands
    subparsers = parser.add_subparsers(dest='mode',
                                       help='Operation mode')

    # Monitor mode
    monitor_parser = subparsers.add_parser('monitor',
                                           help='Monitor Frigate events')
    monitor_parser.add_argument('--duration', type=int, default=0,
                                help='Duration to monitor in seconds (0 = infinite)')

    # List cameras mode
    list_parser = subparsers.add_parser('list-cameras',
                                        help='List all discovered cameras and their info')
    list_parser.add_argument('--wait', type=int, default=3,
                            help='Time to wait for camera discovery in seconds (default: 3)')

    # Command mode
    command_parser = subparsers.add_parser('command',
                                           help='Send command to Frigate')
    command_parser.add_argument('--camera',
                                help='Camera name (required for camera-specific commands)')
    command_parser.add_argument('--command', required=True,
                                help='Command to send')
    command_parser.add_argument('--value', type=int,
                                help='Value for threshold/area commands')
    command_parser.add_argument('--event-id',
                                help='Event ID for review status')
    command_parser.add_argument('--status',
                                help='Review status value')

    args = parser.parse_args()

    if not args.mode:
        parser.print_help()
        return 1

    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create client
    client = FrigateMQTTClient(
        mqtt_host=args.host,
        mqtt_port=args.port,
        mqtt_username=args.username,
        mqtt_password=args.password,
        base_topic=args.base_topic
    )

    # Connect to MQTT broker
    print(f"Connecting to MQTT broker at {args.host}:{args.port}...")
    if not client.connect():
        print("Failed to connect to MQTT broker")
        return 1

    print("Connected successfully!")

    try:
        cli = FrigateCLI(client)

        if args.mode == 'monitor':
            cli.run_monitor(args.duration)
        elif args.mode == 'list-cameras':
            cameras = client.get_cameras()
            if not cameras:
                print("No cameras discovered.")
            else:
                print(f"\nDiscovered {len(cameras)} camera(s):\n")
                for cam_name, cam_info in sorted(cameras.items()):
                    print(f"Camera: {cam_name}")
                    if cam_info.enabled is not None:
                        print(f"  Enabled: {cam_info.enabled}")
                    if cam_info.detect_state is not None:
                        print(f"  Detection: {cam_info.detect_state}")
                    if cam_info.motion_state is not None:
                        print(f"  Motion: {cam_info.motion_state}")
                    if cam_info.audio_state is not None:
                        print(f"  Audio: {cam_info.audio_state}")
                    if cam_info.recordings_state is not None:
                        print(f"  Recordings: {cam_info.recordings_state}")
                    if cam_info.snapshots_state is not None:
                        print(f"  Snapshots: {cam_info.snapshots_state}")
                    if cam_info.camera_fps is not None:
                        print(f"  Camera FPS: {cam_info.camera_fps:.1f}")
                    if cam_info.detection_fps is not None:
                        print(f"  Detection FPS: {cam_info.detection_fps:.1f}")
                    if cam_info.process_fps is not None:
                        print(f"  Process FPS: {cam_info.process_fps:.1f}")
                    if cam_info.motion_threshold is not None:
                        print(f"  Motion Threshold: {cam_info.motion_threshold}")
                    if cam_info.motion_contour_area is not None:
                        print(f"  Motion Contour Area: {cam_info.motion_contour_area}")
                    print()
        elif args.mode == 'command':
            # Validate camera argument for camera-specific commands
            camera_commands = [
                'enable-recording', 'disable-recording',
                'enable-detection', 'disable-detection',
                'take-snapshot',
                'enable-motion', 'disable-motion', 'improve-contrast',
                'enable-audio', 'disable-audio',
                'enable-camera', 'disable-camera',
                'enable-snapshots', 'disable-snapshots',
                'set-motion-threshold', 'set-motion-contour-area',
                'enable-ptz-autotrack', 'disable-ptz-autotrack'
            ]

            if args.command in camera_commands or args.command.startswith('ptz-'):
                if not args.camera:
                    print(f"Error: --camera is required for command '{args.command}'")
                    return 1

            cli.run_command(args)
            time.sleep(1)  # Give time for command to be sent

    finally:
        client.disconnect()
        print("Disconnected from MQTT broker")

    return 0


if __name__ == '__main__':
    sys.exit(main())
