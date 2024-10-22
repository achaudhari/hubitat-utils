#!/usr/bin/env python3

import os
import logging
import json
import argparse
import tempfile
from datetime import datetime
import subprocess

import dominate
from dominate.tags import *
from dominate.util import text
from sensordb_client import SensorDbClient, SensorHist
from webshot_ffox import WebScreenshotFirefox
from common import EmailUtils

def meas_dev(pair):
    return pair['meas'], pair['device']

class HistoryReportGen:
    def __init__(self, cfg_file, cred_file):
        self.dbcli = SensorDbClient(cred_file)
        with open(cfg_file) as json_f:
            self.senscfg = json.load(json_f)

    def grafana_link(self, dashboard, t_strt, t_stop):
        addr = self.senscfg['dashboard']['address']
        ids = self.senscfg['dashboard']['ids']
        ms_strt = int(t_strt.timestamp() * 1000)
        ms_stop = int(t_stop.timestamp() * 1000)
        return f'http://{addr}/d/{ids[dashboard]}?orgId=1&from={ms_strt}&to={ms_stop}&kiosk'

    def send_email(self, t_strt, t_stop, email_addr):
        logging.info('HistoryReportGen: Pulling data from influxdb...')
        event_log = []
        door_tbl = [('Door', 'Opens')]
        for d in self.senscfg['doors']:
            meas, dev = meas_dev(d['status'])
            sens = SensorHist(self.dbcli, meas, dev, t_strt, t_stop)
            opens = len([ts for ts, val in sens.calc_transitions() if val < 0])
            door_tbl.append((d['name'], str(opens)))
            for ts, val in sens.calc_transitions():
                event_log.append((ts, f'{d["name"]} {("OPENED" if val < 0 else "CLOSED")}'))
        motion_tbl = [('Zone', 'Activity Factor')]
        for d in self.senscfg['motion-zones']:
            meas, dev = meas_dev(d['status'])
            sens = SensorHist(self.dbcli, meas, dev, t_strt, t_stop)
            stats = sens.calc_stats()
            motion_tbl.append((d['name'], f'{int(stats["mean"]*100):d}%'))
        camera_tbl = [('Camera', 'Person', 'Motion', 'Sound', 'Online')]
        for d in self.senscfg['cameras']:
            vals = []
            for m in ['person', 'motion', 'sound', 'online']:
                if m in d:
                    meas, dev = meas_dev(d[m])
                    sens = SensorHist(self.dbcli, meas, dev, t_strt, t_stop)
                    if m == 'online':
                        stats = sens.calc_stats()
                        val = f'{int(stats["mean"]*100):d}%' if 'mean' in stats else '0%'
                    else:
                        events = [ts for ts, val in sens.calc_transitions() if val > 0]
                        val = str(len(events))
                        if m == 'person':
                            for ts in events:
                                event_log.append((ts, f'{d["name"]} PERSON'))
                else:
                    val = ''
                vals.append(val)
            camera_tbl.append((d['name'], *tuple(vals)))
        event_log.sort()

        logging.info('HistoryReportGen: Starting browser...')
        webshot = WebScreenshotFirefox()
        logging.info('HistoryReportGen: Taking grafana screenshots...')
        imgs = {
            'timeline_dashboard': tempfile.mktemp(suffix='.png'),
            'environmental_dashboard': tempfile.mktemp(suffix='.png'),
        }
        webshot.take(self.grafana_link('timeline', t_strt, t_stop),
            imgs['timeline_dashboard'], 5.0, 1080, 1850)
        webshot.take(self.grafana_link('environmental', t_strt, t_stop),
            imgs['environmental_dashboard'], 3.0, 1080, 1050)

        logging.info('HistoryReportGen: Generating HTML...')
        title = 'Sensor History Report'
        doc = dominate.document(title=title, doctype=None)
        with doc:
            style("""\
                    table, th, td {
                        border: 1px solid;
                        border-collapse: collapse;
                    }
                    th, td {
                        padding-top: 3px; padding-bottom: 3px;
                        padding-left: 5px; padding-right: 5px;
                    }
                  """)
            h2(title)
            p(f'{t_strt.strftime("%Y-%m-%d %l:%M:%S %p")} - {t_stop.strftime("%Y-%m-%d %l:%M:%S %p")}',
              style="font-weight: bold; color:blue")
            with h3():
                u('Activity Timeline')
            img(src="cid:timeline_dashboard")
            with h3():
                u('Environmental')
            img(src="cid:environmental_dashboard")
            tbl_def = [('Door Summary', door_tbl), 
                       ('Motion Summary', motion_tbl), ('Camera Summary', camera_tbl)]
            for tname, tdata in tbl_def:
                with h3():
                    u(tname)
                with table().add(tbody()):
                    for nrow, trow in enumerate(tdata):
                        with tr():
                            for tcell in trow:
                                td(tcell, style=('font-weight: bold;' if nrow == 0 else ''))
            with h3():
                u('Event Log')
            with table().add(tbody()):
                with tr():
                    td('Time', style='font-weight: bold;')
                    td('Event', style='font-weight: bold;')
                for trow in event_log:
                    with tr():
                        ts, evnt = trow
                        td(ts.strftime("%Y-%m-%d %l:%M:%S %p"))
                        td(evnt)

        logging.info('HistoryReportGen: Sending email...')
        subject = f'INFO: Sensor History ({t_stop.strftime("%Y-%m-%d")})'
        EmailUtils.send_email_html(email_addr, subject, str(doc), imgs)
        os.unlink(imgs['timeline_dashboard'])
        os.unlink(imgs['environmental_dashboard'])
        logging.info('HistoryReportGen: Email sent')


class NetworkReportGen:
    def __init__(self, clients, verbosity):
        self.curr_clients = clients
        self.verbosity = verbosity

    def send_email(self, email_addr):
        logging.info('NetworkReportGen: Generating network report HTML...')
        report_time = datetime.now()
        title = 'Network Report'
        doc = dominate.document(title=title, doctype=None)
        with doc:
            style("""\
                    table, th, td {
                        border: 1px solid;
                        border-collapse: collapse;
                    }
                    th, td {
                        padding-top: 3px; padding-bottom: 3px;
                        padding-left: 5px; padding-right: 5px;
                    }
                  """)
            h2(title)
            p(f'{report_time.strftime("%Y-%m-%d %l:%M:%S %p")}',
              style="font-weight: bold; color:blue")
            with h3():
                u('Connected Devices')
            with table().add(tbody()):
                with tr():
                    for hdr in ['IP Address', 'MAC Address', 'Vendor', 'Name']:
                        td(hdr, style='font-weight: bold;')
                for nrow, trow in enumerate(self.curr_clients):
                    with tr():
                        for tcell in trow:
                            td(tcell)
            if self.verbosity in ['full']:
                logging.info('NetworkReportGen: Running DNS leak test...')
                dnsleak_out = subprocess.check_output('dnsleaktest.sh', shell=True).strip().decode('utf-8')
                with h3():
                    u('DNS Leak Test Report')
                with pre():
                    for line in dnsleak_out.split('\n'):
                        text(line)
                        br()
            if self.verbosity in ['full']:
                logging.info('NetworkReportGen: Running internet speed test...')
                speedtest_out = subprocess.check_output('speedtest', shell=True).strip().decode('utf-8')
                with h3():
                    u('Internet Speed Test Report')
                with pre():
                    for line in speedtest_out.split('\n'):
                        text(line)
                        br()

        logging.info('NetworkReportGen: Sending email...')
        subject = f'INFO: Network Report ({report_time.strftime("%Y-%m-%d")})'
        EmailUtils.send_email_html(email_addr, subject, str(doc))
        logging.info('NetworkReportGen: Email sent')


def main():
    parser = argparse.ArgumentParser(description='Hubitat Event Notifier Daemon')
    parser.add_argument('--cfg-json', type=str, default=None, help='Path to JSON config file')
    parser.add_argument('--creds', type=str, required=True, help='Path to credentials file')
    parser.add_argument('--email', type=str, required=True, help='Email address')
    parser.add_argument('--start', type=str, default=None, help='Start timestamp (%Y-%m-%d %H:%M:%S)')
    parser.add_argument('--stop', type=str, default=None, help='Stop timestamp (%Y-%m-%d %H:%M:%S)')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    t_strt = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S") if args.start else None
    t_stop = datetime.strptime(args.stop, "%Y-%m-%d %H:%M:%S") if args.stop else datetime.now()

    rgen = HistoryReportGen(args.cfg_json, args.creds)
    rgen.send_email(t_strt, t_stop, args.email)

if __name__ == '__main__':
    main()
