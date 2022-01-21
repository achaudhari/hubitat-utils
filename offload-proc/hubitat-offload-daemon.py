#!/usr/bin/env python3
import os, sys
import subprocess
import time
import logging
import argparse
import random
import datetime
import tempfile
import requests

import email
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import mimetypes

from werkzeug.wrappers import Request, Response
from werkzeug.serving import run_simple
from jsonrpc import JSONRPCResponseManager, dispatcher
from selenium import webdriver
from selenium.webdriver.firefox.options import Options

def get_host_ip_addr():
    cmd = "hostname -i | awk '{print $1}'"
    return subprocess.check_output(cmd, shell=True).strip().decode('utf-8')

RPC_PORT = 4226

# ---------------------------------------
#   Email Utilities
# ---------------------------------------
class EmailUtils:
    @staticmethod
    def _send_msg(msg):
        with tempfile.NamedTemporaryFile(suffix='.eml', delete=False) as eml_f:
            eml_f.write(msg.as_bytes())
            eml_f.flush()
            subprocess.check_call(f'sendmail -t < {eml_f.name}', shell=True)

    @staticmethod
    def send_email_text(email_addr, subject, body):
        msg = MIMEMultipart()
        msg['To'] = email_addr
        msg['From'] = f'Automation Bot <{email_addr}>'
        msg['In-Reply-To'] = msg['From']
        msg['Subject'] = subject
        msg['Message-Id'] = f'<{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.{"%016x" % random.randrange(16 ** 16)}@hauto-offload.local>'
        body = MIMEText(f'<html><body>{body}</body></html>', _subtype='html')
        msg.attach(body)
        EmailUtils._send_msg(msg)

    @staticmethod
    def send_email_image(email_addr, subject, img_fname):
        msg = MIMEMultipart()
        msg['To'] = email_addr
        msg['From'] = f'Automation Bot <{email_addr}>'
        msg['In-Reply-To'] = msg['From']
        msg['Subject'] = subject
        msg['Message-Id'] = f'<{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.{"%016x" % random.randrange(16 ** 16)}@hauto-offload.local>'
        message = '<html><body><img src="cid:img_payload"/></body></html>'
        body = MIMEText(message, _subtype='html')
        msg.attach(body)
        with open(img_fname, 'rb') as fd:
            mimetype, mimeencoding = mimetypes.guess_type(img_fname)
            if mimeencoding or (mimetype is None):
                mimetype = 'application/octet-stream'
            maintype, subtype = mimetype.split('/')
            if maintype == 'text':
                attachment = MIMEText(fd.read(), _subtype=subtype)
            else:
                attachment = MIMEBase(maintype, subtype)
                attachment.set_payload(fd.read())
                email.encoders.encode_base64(attachment)
            attachment.add_header('Content-ID', '<img_payload>')
            attachment.add_header('Content-Disposition', 'inline', filename=img_fname)
        msg.attach(attachment)
        EmailUtils._send_msg(msg)

def rpc_email_text(email_addr, subject, email_body):
    logging.info(f'rpc_email_text(email_addr={email_addr}, subject={subject}, '
        f'email_body={email_body})')
    EmailUtils.send_email_text(email_addr, subject, email_body)
    logging.info('rpc_email_text: Finished successfully')

def rpc_email_web_snapshot(email_addr, subject, page_url, page_wd, page_ht, load_delay):
    logging.info(f'rpc_email_web_snapshot(email_addr={email_addr}, subject={subject}, '
        f'page_url={page_url}, page_wd={page_wd}, page_ht={page_ht}, load_delay={load_delay})')
    # Open headless firefox and resize window
    logging.info('rpc_email_web_snapshot: Starting browser...')
    options = Options()
    options.headless = True
    driver = webdriver.Firefox(options=options)
    driver.set_window_position(0, 0)
    driver.set_window_size(page_wd, page_ht)
    # Load URL and save screenshot
    logging.info('rpc_email_web_snapshot: Loading page and saving screenshot...')
    driver.get(page_url)
    time.sleep(load_delay)
    dashboard_img_path = tempfile.mktemp(suffix='.png')
    driver.save_screenshot(dashboard_img_path)
    # Create email and send
    logging.info('rpc_email_web_snapshot: Sending email...')
    EmailUtils.send_email_image(email_addr, subject, dashboard_img_path)
    # Cleanup
    os.unlink(dashboard_img_path)
    driver.quit()
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
        reported = full["state"]["reported"]
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
                15 : 'Low Battery',
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

def rpc_sleep(duration_s):
    logging.info(f'rpc_sleep(duration_s={duration_s})')
    time.sleep(duration_s)
    return 0

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

    response = JSONRPCResponseManager.handle(
        request.data, dispatcher)
    return Response(response.json, mimetype='application/json')

def main():
    parser = argparse.ArgumentParser(description='Hubitat Offload Daemon')
    parser.add_argument('--rpc-addr', type=str, default=get_host_ip_addr(), help='IP address to bing server to')
    parser.add_argument('--rpc-port', type=int, default=RPC_PORT, help='TCP port to listen on')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    run_simple(args.rpc_addr, args.rpc_port, application)

if __name__ == '__main__':
    main()
