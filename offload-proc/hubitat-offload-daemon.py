#!/usr/bin/env python3
import os, sys
import subprocess
import time
import logging
import argparse
import datetime

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

RPC_ADDR = get_host_ip_addr()
RPC_PORT = 4226

def send_page_snapshot_email(email_addr, subject, snapshot_img):
    msg = MIMEMultipart()
    msg['To'] = email_addr
    msg['From'] = f'Hubitat Automation <{email_addr}>'
    msg['Subject'] = subject
    message = '<html><body><img src="cid:snapshot_img"/></body></html>'
    body = MIMEText(message, _subtype='html')
    msg.attach(body)
    with open(snapshot_img, 'rb') as fd:
        mimetype, mimeencoding = mimetypes.guess_type(snapshot_img)
        if mimeencoding or (mimetype is None):
            mimetype = 'application/octet-stream'
        maintype, subtype = mimetype.split('/')
        if maintype == 'text':
            attachment = MIMEText(fd.read(), _subtype=subtype)
        else:
            attachment = MIMEBase(maintype, subtype)
            attachment.set_payload(fd.read())
            email.encoders.encode_base64(attachment)
        attachment.add_header('Content-ID', '<snapshot_img>')
        attachment.add_header('Content-Disposition', 'inline',
            filename = snapshot_img)
    msg.attach(attachment)
    eml_fname = '/tmp/snapshot.eml'
    with open(eml_fname, 'w') as eml_f:
        eml_f.write(msg.as_string())
    subprocess.check_call(f'sendmail -t < {eml_fname}', shell=True)
    os.remove(eml_fname)

def rpc_email_dashboard(email_addr, dashboard_name, page_wd, page_ht, load_delay):
    logging.info(f'email_dashboard(email_addr={email_addr}, dashboard_name={dashboard_name}, '
                 f'page_wd={page_wd}, page_ht={page_ht}, load_delay={load_delay})')
    logging.info('email_dashboard: Starting browser...')
    options = Options()
    options.headless = True
    driver = webdriver.Firefox(options=options)
    driver.set_window_position(0, 0)
    driver.set_window_size(page_wd, page_ht)
    logging.info('email_dashboard: Saving dashboard...')
    driver.get(f'http://{RPC_ADDR}/{dashboard_name}')
    time.sleep(load_delay)
    dashboard_img_path = f'/tmp/{dashboard_name}.png'
    driver.save_screenshot(dashboard_img_path)
    logging.info('email_dashboard: Sending email...')
    datestr = datetime.datetime.now().strftime('%d-%b-%Y')
    send_page_snapshot_email(email_addr, f'INFO: Hubigraph Snapshot ({datestr})', dashboard_img_path)
    os.remove(dashboard_img_path)
    driver.quit()
    logging.info('email_dashboard: DONE')

def rpc_echo(data):
    return data

@Request.application
def application(request):
    dispatcher["echo"] = rpc_echo
    dispatcher["email_dashboard"] = rpc_email_dashboard

    response = JSONRPCResponseManager.handle(
        request.data, dispatcher)
    return Response(response.json, mimetype='application/json')

def main():
    parser = argparse.ArgumentParser(description='Hubitat Offload Daemon')
    parser.add_argument('--rpc-port', type=int, default=RPC_PORT, help='TCP port to listen on')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    run_simple(RPC_ADDR, args.rpc_port, application)

if __name__ == '__main__':
    main()
