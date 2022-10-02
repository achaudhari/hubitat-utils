#!/usr/bin/env python3
import os, sys
import subprocess
import time
import logging
import argparse
import random
import tempfile
import requests

from werkzeug.wrappers import Request, Response
from werkzeug.serving import run_simple
from jsonrpc import JSONRPCResponseManager, dispatcher
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings

from common import EmailUtils

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CFG_DIR = '/home/admin/cfg'
RPC_PORT = 4226

def get_host_ip_addr():
    cmd = "hostname -i | awk '{print $1}'"
    return subprocess.check_output(cmd, shell=True).strip().decode('utf-8')

def rpc_email_text(email_addr, subject, email_body):
    email_body = email_body.replace('\n', '<br>').replace('\t', '&emsp;')
    logging.info(f'rpc_email_text(email_addr={email_addr}, subject={subject}, '
        f'email_body={email_body})')
    EmailUtils.send_email_text(email_addr, subject, email_body)
    logging.info('rpc_email_text: Finished successfully')

def rpc_email_web_snapshot(email_addr, subject, page_url, load_delay):
    logging.info(f'rpc_email_web_snapshot(email_addr={email_addr}, subject={subject}, '
        f'page_url={page_url}, load_delay={load_delay})')

    # Load URL and save screenshot
    logging.info('rpc_email_web_snapshot: Loading page and saving screenshot...')
    dashboard_img_path = tempfile.mktemp(suffix='.png')
    script = os.path.join(SCRIPT_DIR, 'web-screenshot.sh')
    os.system(f'bash {script} {page_url} {int(load_delay * 1e3)} {dashboard_img_path}')

    # Create email and send
    logging.info('rpc_email_web_snapshot: Sending email...')
    EmailUtils.send_email_image(email_addr, subject, dashboard_img_path)
    # Cleanup
    os.unlink(dashboard_img_path)
    logging.info('rpc_email_web_snapshot: Finished successfully')

# ---------------------------------------
#   Roomba Utilities
# ---------------------------------------
class RoombaUtils:
    STATE_URL = 'http://localhost:8200/api/local/info/state'
    ACTION_URL_BASE = 'http://localhost:8200/api/local/action/'

    @staticmethod
    def get_full_state():
        response = requests.get(RoombaUtils.STATE_URL)
        return response.json()

    @staticmethod
    def get_reduced_state():
        full = RoombaUtils.get_full_state()
        if full['state'] is None:
            raise IOError(f'Empty state. Roomba might be offline.')
        reported = full['state']['reported']
        pretty_state = {
            'name': reported['name'],
            'battery': reported['batPct'],
            'wifi_rssi': reported['signal']['rssi'],
            'mission_sqft': reported['cleanMissionStatus']['sqft'],
            'last_cmd': reported['lastCommand']['command'],
            'last_cmd_time': reported['lastCommand']['time'],
        }
        try:
            pretty_state['ready_msg'] = 'Ready: ' + {
                0  : 'Okay',
                2  : 'Uneven Ground',
                7  : 'Bin Detached',
                15 : 'Low Battery',
                16 : 'Bin Full',
                39 : 'Pending',
                48 : 'Path Blocked',
            }[reported['cleanMissionStatus']['notReady']]
        except KeyError:
            pretty_state['ready_msg'] = f"Ready: Unknown{reported['cleanMissionStatus']['notReady']}"
        try:
            pretty_state['error_msg'] = 'Status: ' + {
                0  : 'Okay',
                15 : 'Reboot Required',
                18 : 'Docking Issue',
            }[reported['cleanMissionStatus']['error']]
        except KeyError:
            pretty_state['error_msg'] = f"Status: Unknown{reported['cleanMissionStatus']['error']}"
        if reported['cleanMissionStatus']['phase'] == 'charge' and reported['batPct'] == 100:
            pretty_state['phase'] = 'Roomba Idle'
        elif reported['cleanMissionStatus']['cycle'] == 'none' and reported['cleanMissionStatus']['phase'] == 'stop':
            pretty_state['phase'] = 'Roomba Stopped'
        else:
            try:
                pretty_state['phase'] = 'Roomba ' + {
                    'charge'    : 'Charging',
                    'run'       : 'Running',
                    'evac'      : 'Empty',
                    'stop'      : 'Paused',
                    'stuck'     : 'Stuck',
                    'hmUsrDock' : 'Sent Home',
                    'hmMidMsn'  : 'Mid Dock',
                    'hmPostMsn' : 'Final Dock' 
                }[reported['cleanMissionStatus']['phase']]
            except KeyError:
                pretty_state['phase'] = 'Roomba ' + reported['cleanMissionStatus']['phase']
        pretty_state['bin_status'] = {
            (False, False)  : 'Bin Detached',
            (False, True)   : 'Bin Detached',
            (True, False)   : 'Bin Not Full',
            (True, True)    : 'Bin Full',
        }[(reported['bin']['present'], reported['bin']['full'])]
        return pretty_state

    @staticmethod
    def send_cmd(action):
        ALL_ACTIONS = ['start', 'stop', 'pause', 'resume', 'dock', 'reset', 'locate']
        if action in ALL_ACTIONS:
            response = requests.get(RoombaUtils.ACTION_URL_BASE + action)
        else:
            raise ValueError(f'Invalid action={action}. Must be {" ".join(ALL_ACTIONS)}')

def rpc_roomba_get_state(what):
    logging.info(f'rpc_roomba_get_state(what={what})')
    if what == 'full':
        return RoombaUtils.get_full_state()
    elif what == 'reduced':
        return RoombaUtils.get_reduced_state()
    else:
        raise ValueError(f'Invalid what={what}. Must be full/reduced.')

def rpc_roomba_send_cmd(action):
    logging.info(f'rpc_roomba_send_cmd(action={action})')
    RoombaUtils.send_cmd(action)

# ---------------------------------------
#   Motion daemon Utilities
# ---------------------------------------
class MotionUtils:
    BASE_URL = 'http://localhost:3724'

    @staticmethod
    def send_cmd(cam_id, cmd):
        CMD_MAP = {
            'restart': 'action/end',
            'eventstart': 'action/eventstart',
            'eventend': 'action/eventend',
            'status': 'detection/connection'
        }
        response = requests.get(f'{MotionUtils.BASE_URL}/{cam_id}/{CMD_MAP[cmd]}')
        return [response.text]

def rpc_motion_send_cmd(cam_id, cmd):
    logging.info(f'rpc_motion_send_cmd(cam_id={cam_id}, cmd={cmd})')
    return MotionUtils.send_cmd(cam_id, cmd)

# ---------------------------------------
#   Generic
# ---------------------------------------

def rpc_echo(data):
    logging.info(f'rpc_echo(data={data})')
    return data

def rpc_sleep(duration_s):
    logging.info(f'rpc_sleep(duration_s={duration_s})')
    time.sleep(duration_s)
    return 0

def hub_authenticate(cookie):
    with open(os.path.join(CFG_DIR, 'hubitat.secret'), 'r') as sec_f:
        shared_sec = sec_f.readline().strip()
    # Encrypted using $ cat /sys/class/net/eth0/address | cut -c -18 | openssl enc -e -des3 -base64 -pass pass:${shared_sec} -pbkdf2
    try:
        resp_rem = subprocess.check_output(
            f'echo "{cookie}" | openssl enc -d -des3 -base64 -pass pass:{shared_sec} -pbkdf2',
            shell=True).strip().decode('utf-8')
        resp_lcl = subprocess.check_output('cat /sys/class/net/eth0/address',
            shell=True).strip().decode('utf-8')
    except:
        raise PermissionError('Secret validation failed. Permission denied.')
    if resp_rem != resp_lcl:
        raise PermissionError('Secret validation failed. Permission denied.')

def rpc_reboot_sys(cookie):
    logging.info(f'rpc_reboot_sys(cookie={cookie})')
    hub_authenticate(cookie)
    logging.info('rpc_reboot_sys: Permission granted. Rebooting system...')
    subprocess.Popen(['sleep 3; sudo /sbin/reboot'], shell=True) # Nonblocking
    return cookie

def rpc_shutdown_sys(cookie):
    logging.info(f'rpc_shutdown_sys(cookie={cookie})')
    hub_authenticate(cookie)
    logging.info('rpc_shutdown_sys: Permission granted. Shutting system down...')
    subprocess.Popen(['sleep 3; sudo /sbin/shutdown -h now'], shell=True) # Nonblocking
    return cookie

def rpc_hub_safe_shutdown(cookie):
    logging.info(f'rpc_hub_safe_shutdown(cookie={cookie})')
    hub_authenticate(cookie)
    logging.info('rpc_hub_safe_shutdown: Permission granted. Shutting down hub...')
    os.system(f'bash {os.path.join(SCRIPT_DIR, "hubitat-admin-ctrl.sh")} shutdown')
    return cookie

# ---------------------------------------
#   Main application
# ---------------------------------------

@Request.application
def application(request):
    dispatcher["echo"] = rpc_echo
    dispatcher["sleep"] = rpc_sleep
    dispatcher["email_web_snapshot"] = rpc_email_web_snapshot
    dispatcher["email_text"] = rpc_email_text
    dispatcher["roomba_get_state"] = rpc_roomba_get_state
    dispatcher["roomba_send_cmd"] = rpc_roomba_send_cmd
    dispatcher["motion_send_cmd"] = rpc_motion_send_cmd
    dispatcher["reboot"] = rpc_reboot_sys
    dispatcher["shutdown"] = rpc_shutdown_sys
    dispatcher["hub_safe_shutdown"] = rpc_hub_safe_shutdown

    response = JSONRPCResponseManager.handle(request.data, dispatcher)
    return Response(response.json, mimetype='application/json')

def main():
    parser = argparse.ArgumentParser(description='Hubitat Offload Daemon')
    parser.add_argument('--rpc-addr', type=str, default=get_host_ip_addr(), help='IP address to bing server to')
    parser.add_argument('--rpc-port', type=int, default=RPC_PORT, help='TCP port to listen on')
    parser.add_argument('--processes', type=int, default=3, help='Max number of processes')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    run_simple(args.rpc_addr, args.rpc_port, application, processes=args.processes)

if __name__ == '__main__':
    main()
