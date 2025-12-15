#!/usr/bin/env python3
"""
Lightweight system management service for system home automation offload engine.
Runs in a privileged systemd service and accepts authenticated HTTP requests.
"""
import os
import argparse
import subprocess
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import hashlib
import hmac
import json
import time
import docker

# pylint: disable=C0113,C0114,C0115,C0116,C0103

LISTEN_PORT = 4227
SECRET_FILE = '/srv/hubitat-utils/config/sysmgmtd-secret.txt'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_host_ip_addr(wait_for_network = True, timeout = 30):
    def get_ip():
        cmd = "hostname -i | awk '{print $1}'"
        return subprocess.check_output(cmd, shell=True).strip().decode('utf-8')
    ip = get_ip()
    elapsed = 0
    # Retry command until loopback interface addr disappears
    while wait_for_network and ip.split('.', maxsplit=1)[0] not in ['192']:
        if elapsed >= timeout:
            break
        elapsed += 1
        time.sleep(1.0)
        print('WARNING: Network is initializing. Retrying host IP...')
        ip = get_ip()
    return ip


class HAutoSysMgmtDaemon(BaseHTTPRequestHandler):
    def __init__(self, *args, secret: str = '', **kwargs):
        self._secret = secret
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args) -> None:  # pylint: disable=W0622
        """Override to use logging module"""
        logging.info("%s - - " + format, self.address_string(), *args)

    def verify_auth(self):
        """Verify HMAC authentication"""
        auth_header = self.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return False

        token = auth_header[7:]  # Remove 'Bearer ' prefix
        expected = hmac.new(
            self._secret.encode(),
            self.path.encode(),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(token, expected)

    def send_json_response(self, code, data):
        """Send JSON response"""
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        """Handle GET health check"""
        if self.path == '/health':
            self.send_json_response(200, {'status': 'ok', 'service': 'sysmgmtd'})
        else:
            self.send_json_response(404, {'error': 'Not found'})

    def do_POST(self):
        """Handle POST requests"""
        if not self._secret:
            logging.error('HAUTO_SYSMGMTD_SECRET not set!')
            self.send_json_response(500, {'error': 'Service misconfigured'})
            return

        if not self.verify_auth():
            logging.warning('Unauthorized request from %s', self.address_string())
            self.send_json_response(401, {'error': 'Unauthorized'})
            return

        if self.path == '/reboot':
            self.handle_reboot()
        elif self.path == '/shutdown':
            self.handle_shutdown()
        elif self.path == '/health':
            self.handle_health()
        elif self.path == '/speedtest':
            self.handle_speedtest()
        elif self.path == '/dnsleaktest':
            self.handle_dnsleaktest()
        else:
            self.send_json_response(404, {'error': 'Not found'})

    def handle_reboot(self):
        logging.info('Received reboot command - executing in 3 seconds')
        subprocess.Popen(['sh', '-c', 'sleep 3 && sudo /sbin/reboot'])
        self.send_json_response(200, {'status': 'ok', 'action': 'reboot'})

    def handle_shutdown(self):
        logging.info('Received shutdown command - executing in 3 seconds')
        subprocess.Popen(['sh', '-c', 'sleep 3 && sudo /sbin/poweroff'])
        self.send_json_response(200, {'status': 'ok', 'action': 'shutdown'})

    def handle_health(self):
        fail_cnt = 0
        health = {}
        # Map service names to container names and expected status
        service_checks = {
            'hubitat-offload': {'container': 'hubitat-offload', 'expected_status': 'running'},
            'hubitat-event': {'container': 'hubitat-event', 'expected_status': 'running'},
            'influxdb': {'container': 'influxdb', 'expected_status': 'running'},
            'grafana': {'container': 'grafana', 'expected_status': 'running'},
            'caddy': {'container': 'caddy', 'expected_status': 'running'},
            'cloudflared': {'container': 'grafana', 'expected_status': 'running'},
        }
        try:
            # Connect to Docker daemon via socket
            fail_cnt = 0
            client = docker.DockerClient(base_url='unix://var/run/docker.sock')
            for svc_name, check_info in service_checks.items():
                try:
                    # Get container by name and check its status
                    container = client.containers.get(check_info['container'])
                    status = container.status
                    if status == check_info['expected_status']:
                        health[svc_name] = 'OKAY'
                    else:
                        health[svc_name] = f'UNEXPECTED:{status}'
                        fail_cnt += 1
                except docker.errors.NotFoundException:
                    fail_cnt += 1
                    health[svc_name] = 'NOT_FOUND'
                except Exception as e:  # pylint: disable=broad-exception-caught
                    fail_cnt += 1
                    health[svc_name] = f'ERROR:{str(e)}'
            client.close()
            health['overall'] = 'DEGRADED' if fail_cnt else 'OKAY'
            self.send_json_response(200, {'status': 'ok', 'action': 'health',
                                          'health': health})
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.send_json_response(500, {'error': 'Docker client failed' + str(e)})

    def handle_speedtest(self):
        logging.info('Running speedtest...')
        try:
            cmd_out = subprocess.check_output(
                'speedtest', shell=True
            ).strip().decode('utf-8')
            self.send_json_response(
                200, {'status': 'ok', 'action': 'speedtest', 'output': cmd_out})
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.send_json_response(500, {'error': 'Speedtest failed' + str(e)})

    def handle_dnsleaktest(self):
        logging.info('Running dnsleaktest.sh...')
        try:
            cmd_out = subprocess.check_output(
                'dnsleaktest.sh', shell=True
            ).strip().decode('utf-8')
            self.send_json_response(
                200, {'status': 'ok', 'action': 'dnsleaktest', 'output': cmd_out})
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.send_json_response(500, {'error': 'DNS Leak Test failed' + str(e)})


def main():
    parser = argparse.ArgumentParser(description='Home Automation System Management Daemon')
    parser.add_argument('--listen-addr', type=str, default=get_host_ip_addr(),
        help='IP address to bind server to')
    parser.add_argument('--listen-port', type=int, default=LISTEN_PORT,
        help='TCP port to listen on')
    parser.add_argument('--secret-file', type=str, default=SECRET_FILE,
        help='IP address to bind server to')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    # Read secret from file
    if not os.path.isfile(args.secret_file):
        raise FileNotFoundError(f'Secret file not found: {args.secret_file}')
    with open(args.secret_file, 'r', encoding='utf-8') as f:
        secret = f.read().strip()
    if not secret:
        raise FileNotFoundError(f'Secret file is empty: {args.secret_file}')

    def handler(*handler_args, **handler_kwargs):
        return HAutoSysMgmtDaemon(*handler_args, secret=secret, **handler_kwargs)

    httpd = HTTPServer((args.listen_addr, args.listen_port), handler)
    logging.info('Home Automation System Management Daemon listening on port %s:%d',
                 args.listen_addr, args.listen_port)
    httpd.serve_forever()

if __name__ == '__main__':
    main()
