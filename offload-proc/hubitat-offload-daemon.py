#!/usr/bin/env python3
import os
import subprocess
import time
import datetime
import logging
import argparse
import tempfile
import requests
import pickle
import hashlib
import hmac

from waitress import serve
from werkzeug.wrappers import Request, Response
from jsonrpc import JSONRPCResponseManager, dispatcher
from common import EmailUtils
from reportgen import HistoryReportGen, NetworkReportGen
# from webshot_ffox import WebScreenshotFirefox


SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CFG_DIR = '/etc/hauto'
CACHE_DIR = '/var/hauto'
RPC_PORT = 4226

def get_host_ip_addr(wait_for_network = True, timeout = 30):
    cmd = "hostname -i | awk '{print $1}'"
    get_ip = lambda: subprocess.check_output(cmd, shell=True).strip().decode('utf-8')
    is_lo_addr = lambda ip: ip.split('.')[0] == '127'
    ip = get_ip()
    elapsed = 0
    # Retry command until loopback interface addr disappears
    while wait_for_network and is_lo_addr(ip):
        if elapsed >= timeout:
            break
        elapsed += 1
        time.sleep(1.0)
        print('WARNING: Network is initializing. Retrying host IP...')
        ip = get_ip()
    return ip

def rpc_email_text(email_addr, subject, email_body):
    email_body = email_body.replace('\n', '<br>').replace('\t', '&emsp;')
    logging.info(f'rpc_email_text(email_addr={email_addr}, subject={subject}, '
        f'email_body={email_body})')
    EmailUtils.send_email_text(email_addr, subject, email_body)
    logging.info('rpc_email_text: Finished successfully')

def rpc_email_web_snapshot(email_addr, subject, page_url, load_delay):
    logging.info(f'rpc_email_web_snapshot(email_addr={email_addr}, subject={subject}, '
        f'page_url={page_url}, load_delay={load_delay})')
    raise NotImplementedError('Operation DEPRECATED')
    # # Open headless firefox and resize window
    # logging.info('rpc_email_web_snapshot: Starting browser...')
    # webshot = WebScreenshotFirefox()
    # # Load URL and save screenshot
    # logging.info('rpc_email_web_snapshot: Loading page and saving screenshot...')
    # dashboard_img_path = tempfile.mktemp(suffix='.png')
    # webshot.take(page_url, dashboard_img_path, load_delay, 900)
    # # Create email and send
    # logging.info('rpc_email_web_snapshot: Sending email...')
    # EmailUtils.send_email_image(email_addr, subject, dashboard_img_path)
    # os.unlink(dashboard_img_path)
    # logging.info('rpc_email_web_snapshot: Finished successfully')

def rpc_email_history_report(email_addr, duration_hr):
    logging.info(f'rpc_email_history_report(email_addr={email_addr}, duration_hr={duration_hr})')
    t_stop = datetime.datetime.now()
    t_strt = t_stop - datetime.timedelta(hours=duration_hr)
    rgen = HistoryReportGen(os.path.join(CFG_DIR, 'history-report.json'))
    rgen.send_email(t_strt, t_stop, email_addr)

def rpc_email_network_report(email_addr, verbosity):
    logging.info(f'rpc_email_network_report()')
    with open(os.path.join(CACHE_DIR, 'lanmon_clients.pickle'), 'rb') as handle:
        lanmon_blob = pickle.load(handle)
    rgen = NetworkReportGen(lanmon_blob['clients'], verbosity)
    rgen.send_email(email_addr)

# ---------------------------------------
#   Roomba Utilities
# ---------------------------------------
class RoombaUtils:
    STATE_URL = 'http://roomba-python:8200/api/local/info/state'
    ACTION_URL_BASE = 'http://roomba-python:8200/api/local/action/'

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
#   Generic
# ---------------------------------------

def rpc_echo(data):
    logging.info(f'rpc_echo(data={data})')
    return data

def rpc_check_health():
    logging.info(f'rpc_check_health()')
    fail_cnt = 0
    health = {}
    for svc in ['hubitat-offload', 'hubitat-event', 'roomba-svr']:
        try:
            subprocess.check_output(f'systemctl status {svc}', shell=True, stderr=subprocess.STDOUT)
            health[svc] = 'OKAY'
        except subprocess.CalledProcessError:
            fail_cnt += 1
            health[svc] = 'FAILED'
    health['overall'] = 'DEGRADED' if fail_cnt else 'OKAY'
    return health

def rpc_sleep(duration_s):
    logging.info(f'rpc_sleep(duration_s={duration_s})')
    time.sleep(duration_s)
    return 0

def hub_authenticate(cookie):
    shared_sec = os.environ.get('HUBITAT_SECRET')
    if not shared_sec:
        raise PermissionError('HUBITAT_SECRET environment variable not set. Permission denied.')
    resp_lcl = os.environ.get('ETH_IFACE_MAC')
    if not shared_sec:
        raise PermissionError('ETH_IFACE_MAC environment variable not set. Permission denied.')

    # Cookie is the MAC address encrypted using:
    # $ cat /sys/class/net/wan/address | cut -c -18 | openssl enc -e -des3 -base64 -pass pass:${shared_sec} -pbkdf2
    try:
        resp_rem = subprocess.check_output(
            f'echo "{cookie}" | openssl enc -d -des3 -base64 -pass pass:{shared_sec} -pbkdf2',
            shell=True).strip().decode('utf-8')
    except:
        raise PermissionError('Secret validation failed. Permission denied.')
    if resp_rem != resp_lcl:
        raise PermissionError('Secret validation failed. Permission denied.')

def send_power_mgmt_cmd(action):
    """Send authenticated request to power-mgmt service"""
    secret = os.environ.get('HUBITAT_SECRET')
    if not secret:
        raise PermissionError('HUBITAT_SECRET not set')

    # Generate HMAC token for the endpoint
    endpoint = f'/{action}'
    token = hmac.new(secret.encode(), endpoint.encode(), hashlib.sha256).hexdigest()

    # Send request to power-mgmt container via host network
    url = f'http://power-mgmt:9999{endpoint}'
    headers = {'Authorization': f'Bearer {token}'}

    response = requests.post(url, headers=headers, timeout=5)
    response.raise_for_status()
    return response.json()

def rpc_reboot_sys(cookie):
    logging.info(f'rpc_reboot_sys(cookie={cookie})')
    hub_authenticate(cookie)
    logging.info('rpc_reboot_sys: Permission granted. Sending reboot command to power-mgmt...')
    result = send_power_mgmt_cmd('reboot')
    logging.info(f'rpc_reboot_sys: {result}')
    return cookie

def rpc_shutdown_sys(cookie):
    logging.info(f'rpc_shutdown_sys(cookie={cookie})')
    hub_authenticate(cookie)
    logging.info('rpc_shutdown_sys: Permission granted. Sending shutdown command to power-mgmt...')
    result = send_power_mgmt_cmd('shutdown')
    logging.info(f'rpc_shutdown_sys: {result}')
    return cookie

def rpc_hub_safe_shutdown(cookie):
    logging.info(f'rpc_hub_safe_shutdown(cookie={cookie})')
    hub_authenticate(cookie)
    logging.info('rpc_hub_safe_shutdown: Permission granted. Shutting down hub and system...')
    os.system(f'bash {os.path.join(SCRIPT_DIR, "hubitat-admin-ctrl.sh")} shutdown')
    time.sleep(10.0)
    subprocess.Popen(['sleep 3; sudo /sbin/shutdown -h now'], shell=True) # Nonblocking
    return cookie

# ---------------------------------------
#   Main application
# ---------------------------------------

@Request.application
def application(request):
    dispatcher["echo"] = rpc_echo
    dispatcher["sleep"] = rpc_sleep
    dispatcher["check_health"] = rpc_check_health
    dispatcher["email_web_snapshot"] = rpc_email_web_snapshot
    dispatcher["email_history_report"] = rpc_email_history_report
    dispatcher["email_text"] = rpc_email_text
    dispatcher["roomba_get_state"] = rpc_roomba_get_state
    dispatcher["roomba_send_cmd"] = rpc_roomba_send_cmd
    dispatcher["reboot"] = rpc_reboot_sys
    dispatcher["shutdown"] = rpc_shutdown_sys
    dispatcher["hub_safe_shutdown"] = rpc_hub_safe_shutdown
    dispatcher["email_network_report"] = rpc_email_network_report

    response = JSONRPCResponseManager.handle(
        request.data, dispatcher)
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

    serve(application, host=args.rpc_addr, port=args.rpc_port, threads=args.processes)

if __name__ == '__main__':
    main()
