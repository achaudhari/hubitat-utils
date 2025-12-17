#!/usr/bin/env python3
import os
import time
import datetime
import logging
import argparse
import pickle
import hashlib
import hmac
import requests

from waitress import serve
from werkzeug.wrappers import Request, Response  # type: ignore
from jsonrpc import JSONRPCResponseManager, dispatcher  # type: ignore
from common import EmailUtils
from reportgen import HistoryReportGen, NetworkReportGen
# from webshot_ffox import WebScreenshotFirefox

# pylint: disable=C0113,C0114,C0115,C0116,C0103

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CFG_DIR = '/etc/hauto'
CACHE_DIR = '/var/hauto'

HUBITAT_SECRET_SALT = 'obedient-unbent-scant'
HUBITAT_SECRET_FILE = os.path.join(CFG_DIR, 'hubitat-secret.txt')
SYS_MGMT_SECRET_FILE = os.path.join(CFG_DIR, 'sysmgmtd-secret.txt')
RPC_PORT = 4226
SYS_MGMT_PORT = 4227

NOTIF_FROM_EMAIL = 'hauto@heliologic.xyz'
REPORT_FROM_EMAIL = 'hauto-reports@heliologic.xyz'

def read_secret_file(secret_file: str):
    if not os.path.isfile(secret_file):
        raise FileNotFoundError(f'Secret file not found: {secret_file}')
    with open(secret_file, 'r', encoding='utf-8') as f:
        secret = f.read().strip()
    if not secret:
        raise FileNotFoundError(f'Secret file is empty: {secret_file}')
    return secret

def hub_authenticate(cookie):
    try:
        secret = read_secret_file(HUBITAT_SECRET_FILE)
        token = hmac.new(
            secret.encode(), HUBITAT_SECRET_SALT.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(token, cookie):
            raise PermissionError('Secret validation failed. Permission denied.')
    except Exception as ex:
        raise PermissionError('Secret validation failed. Unknown error.') from ex

def send_sys_mgmt_cmd(action, timeout=5):
    """Send authenticated request to power-mgmt service"""
    # Read secret from file
    secret = read_secret_file(SYS_MGMT_SECRET_FILE)

    # Generate HMAC token for the endpoint
    endpoint = f'/{action}'
    token = hmac.new(secret.encode(), endpoint.encode(), hashlib.sha256).hexdigest()

    # Send request to power-mgmt container via host network
    host_ip = os.environ.get('HOST_IP_ADDR')
    if not host_ip:
        raise PermissionError('HOST_IP_ADDR environment variable not set.')

    url = f'http://{host_ip}:{SYS_MGMT_PORT}{endpoint}'
    headers = {'Authorization': f'Bearer {token}'}

    response = requests.post(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()



def rpc_email_text(email_addr, subject, email_body):
    email_body = email_body.replace('\n', '<br>').replace('\t', '&emsp;')
    logging.info('rpc_email_text(email_addr=%s, subject=%s, email_body=%s)',
                 email_addr, subject, email_body)
    EmailUtils.send_email_text(NOTIF_FROM_EMAIL, email_addr, subject, email_body)
    logging.info('rpc_email_text: Finished successfully')

def rpc_email_history_report(email_addr, duration_hr):
    logging.info('rpc_email_history_report(email_addr=%s, duration_hr=%s)',
                 email_addr, duration_hr)
    t_stop = datetime.datetime.now()
    t_strt = t_stop - datetime.timedelta(hours=duration_hr)
    rgen = HistoryReportGen(os.path.join(CFG_DIR, 'history-report.json'))
    rgen.send_email(t_strt, t_stop, REPORT_FROM_EMAIL, email_addr)

def rpc_email_network_report(email_addr, verbosity):
    logging.info('rpc_email_network_report()')
    with open(os.path.join(CACHE_DIR, 'lanmon_clients.pickle'), 'rb') as handle:
        lanmon_blob = pickle.load(handle)

    test_results = {'speedtest': None, 'dnsleaktest': None}
    for test in test_results:
        logging.info('rpc_email_network_report: Running %s', test)
        result = send_sys_mgmt_cmd(test, timeout=60)
        if 'status' in result and result['status'] == 'ok':
            test_results[test] = result['output']

    rgen = NetworkReportGen(lanmon_blob['clients'], verbosity)
    rgen.send_email(REPORT_FROM_EMAIL, email_addr,
                    test_results['speedtest'], test_results['dnsleaktest'])

# ---------------------------------------
#   Roomba Utilities
# ---------------------------------------
class RoombaUtils:
    STATE_URL = 'http://roomba-python:8200/api/local/info/state'
    ACTION_URL_BASE = 'http://roomba-python:8200/api/local/action/'

    @staticmethod
    def get_full_state():
        response = requests.get(RoombaUtils.STATE_URL, timeout=5)
        return response.json()

    @staticmethod
    def get_reduced_state():
        full = RoombaUtils.get_full_state()
        if full['state'] is None:
            raise IOError('Empty state. Roomba might be offline.')
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
            pretty_state['ready_msg'] = (
                f"Ready: Unknown{reported['cleanMissionStatus']['notReady']}"
            )
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
        elif (reported['cleanMissionStatus']['cycle'] == 'none' and
              reported['cleanMissionStatus']['phase'] == 'stop'):
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
            requests.get(RoombaUtils.ACTION_URL_BASE + action, timeout=5)
        else:
            raise ValueError(f'Invalid action={action}. Must be {" ".join(ALL_ACTIONS)}')

def rpc_roomba_get_state(what):
    logging.info('rpc_roomba_get_state(what=%s)', what)
    if what == 'full':
        return RoombaUtils.get_full_state()
    elif what == 'reduced':
        return RoombaUtils.get_reduced_state()
    else:
        raise ValueError(f'Invalid what={what}. Must be full/reduced.')

def rpc_roomba_send_cmd(action):
    logging.info('rpc_roomba_send_cmd(action=%s)', action)
    RoombaUtils.send_cmd(action)

# ---------------------------------------
#   Generic
# ---------------------------------------

def rpc_echo(data):
    logging.info('rpc_echo(data=%s)', data)
    return data

def rpc_check_health():
    logging.info('rpc_check_health()')
    result = send_sys_mgmt_cmd('health')
    if 'status' in result and result['status'] == 'ok':
        health = result['health']
        logging.info('rpc_check_health: %s', health)
        return health
    else:
        logging.error('rpc_check_health: Error %s', result.get('error'))

def rpc_sleep(duration_s):
    logging.info('rpc_sleep(duration_s=%s)', duration_s)
    time.sleep(duration_s)
    return 0

def rpc_reboot_sys(cookie):
    logging.info('rpc_reboot_sys(cookie=%s)', cookie)
    hub_authenticate(cookie)
    logging.info('rpc_reboot_sys: Permission granted. Sending reboot command to sysmgmtd...')
    result = send_sys_mgmt_cmd('reboot')
    logging.info('rpc_reboot_sys: %s', result)
    return cookie

def rpc_shutdown_sys(cookie):
    logging.info('rpc_shutdown_sys(cookie=%s)', cookie)
    hub_authenticate(cookie)
    logging.info('rpc_shutdown_sys: Permission granted. Sending reboot command to sysmgmtd...')
    result = send_sys_mgmt_cmd('shutdown')
    logging.info('rpc_shutdown_sys: %s', result)
    return cookie

# def rpc_hub_safe_shutdown(cookie):
#     logging.info('rpc_hub_safe_shutdown(cookie=%s)', cookie)
#     hub_authenticate(cookie)
#     logging.info('rpc_hub_safe_shutdown: Permission granted. Shutting down hub and system...')
#     os.system(f'bash {os.path.join(SCRIPT_DIR, "hubitat-admin-ctrl.sh")} shutdown')
#     time.sleep(10.0)
#     subprocess.Popen(['sleep 3; sudo /sbin/shutdown -h now'], shell=True) # Nonblocking
#     return cookie

# ---------------------------------------
#   Main application
# ---------------------------------------

@Request.application
def application(request):
    dispatcher["echo"] = rpc_echo
    dispatcher["sleep"] = rpc_sleep
    dispatcher["check_health"] = rpc_check_health
    dispatcher["email_text"] = rpc_email_text
    dispatcher["email_history_report"] = rpc_email_history_report
    dispatcher["email_network_report"] = rpc_email_network_report
    dispatcher["reboot"] = rpc_reboot_sys
    dispatcher["shutdown"] = rpc_shutdown_sys
    dispatcher["roomba_get_state"] = rpc_roomba_get_state
    dispatcher["roomba_send_cmd"] = rpc_roomba_send_cmd
    # dispatcher["hub_safe_shutdown"] = rpc_hub_safe_shutdown

    response = JSONRPCResponseManager.handle(
        request.data, dispatcher)
    return Response(response.json, mimetype='application/json')

def main():
    parser = argparse.ArgumentParser(description='Hubitat Offload Daemon')
    parser.add_argument('--rpc-addr', type=str, default='0.0.0.0',
                        help='IP address to bing server to')
    parser.add_argument('--rpc-port', type=int, default=RPC_PORT,
                        help='TCP port to listen on')
    parser.add_argument('--processes', type=int, default=3,
                        help='Max number of processes')
    parser.add_argument('--verbose', action='store_true',
                        help='Verbose output')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    serve(application, host=args.rpc_addr, port=args.rpc_port, threads=args.processes)

if __name__ == '__main__':
    main()
