#!/usr/bin/env python3
"""
Lightweight power management service for system reboot/shutdown.
Runs in a privileged container and accepts authenticated HTTP requests.
"""
import os
import subprocess
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import hashlib
import hmac

LISTEN_PORT = 9999
SECRET = os.environ.get('POWER_MGMT_SECRET', '')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class PowerMgmtHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        """Override to use logging module"""
        logging.info("%s - - %s" % (self.address_string(), format % args))

    def verify_auth(self):
        """Verify HMAC authentication"""
        auth_header = self.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return False

        token = auth_header[7:]  # Remove 'Bearer ' prefix
        expected = hmac.new(
            SECRET.encode(),
            self.path.encode(),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(token, expected)

    def send_json_response(self, code, data):
        """Send JSON response"""
        import json
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        """Handle POST requests"""
        if not SECRET:
            logging.error('POWER_MGMT_SECRET not set!')
            self.send_json_response(500, {'error': 'Service misconfigured'})
            return

        if not self.verify_auth():
            logging.warning(f'Unauthorized request from {self.address_string()}')
            self.send_json_response(401, {'error': 'Unauthorized'})
            return

        if self.path == '/reboot':
            logging.info('Received reboot command - executing in 3 seconds')
            os.system('sleep 3 && /usr/sbin/reboot')
            self.send_json_response(200, {'status': 'ok', 'action': 'reboot'})

        elif self.path == '/shutdown':
            logging.info('Received shutdown command - executing in 3 seconds')
            os.system('sleep 3 && /usr/sbin/poweroff')
            self.send_json_response(200, {'status': 'ok', 'action': 'shutdown'})

        elif self.path == '/health':
            self.send_json_response(200, {'status': 'ok', 'service': 'power-mgmt'})

        else:
            self.send_json_response(404, {'error': 'Not found'})

    def do_GET(self):
        """Handle GET health check"""
        if self.path == '/health':
            self.send_json_response(200, {'status': 'ok', 'service': 'power-mgmt'})
        else:
            self.send_json_response(404, {'error': 'Not found'})

def main():
    if not SECRET:
        logging.error('POWER_MGMT_SECRET environment variable not set!')
        logging.error('Service will reject all requests.')

    server_address = ('0.0.0.0', LISTEN_PORT)
    httpd = HTTPServer(server_address, PowerMgmtHandler)
    logging.info(f'Power management service listening on port {LISTEN_PORT}')
    logging.info('Supported endpoints: POST /reboot, POST /shutdown, GET /health')
    httpd.serve_forever()

if __name__ == '__main__':
    main()
