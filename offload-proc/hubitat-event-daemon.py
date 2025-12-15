#!/usr/bin/env python3
import subprocess
import time
import logging
import json
import argparse
import random
import requests
from lanmon import LanMonitor

# pylint: disable=C0113,C0114,C0115,C0116,C0103

class Worker:
    def __init__(self, dev, hub_xact_fn):
        self.dev = dev
        self._hub_xact_fn = hub_xact_fn
        start_offs = random.randrange(0, self.dev['poll-interval'])
        self._next_run_time = time.time() + start_offs

    def work_if_due(self):
        time_now = time.time()
        if time_now > self._next_run_time:
            self.work()
            self._next_run_time = time_now + self.dev['poll-interval']
            logging.debug('%s: %s::work() finished in %.3fs', self.dev["name"],
                          self.dev["worker"], (time.time()-time_now))
    def hub_transact(self, *args, **kwargs):
        return self._hub_xact_fn(*args, **kwargs)

class Pinger(Worker):
    def __init__(self, dev, hub_xact_fn, _):
        super(Pinger, self).__init__(dev, hub_xact_fn)
        self.ip_addr = dev['worker-args']['addr']
        self.is_online = None
        self.ping_proc = None

    def work(self):
        dispatch_ping = False
        if self.ping_proc is not None:
            if self.ping_proc.poll() is not None:
                self.ping_proc.communicate()
                dispatch_ping = True
                curr_online = self.ping_proc.returncode == 0
                if self.is_online != curr_online:
                    self.hub_transact('dev_cmd', dev_id=self.dev['id'],
                        cmd=('arrived' if curr_online else 'departed'))
                    logging.info('%s: Online status changed to %s',
                                 self.dev["name"], curr_online)
                self.is_online = curr_online
        else:
            dispatch_ping = True
        if dispatch_ping:
            self.ping_proc = subprocess.Popen(['ping', self.ip_addr, '-i', '0.5', '-c', '5'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

class InternetChecker(Worker):
    def __init__(self, dev, hub_xact_fn, _):
        super(InternetChecker, self).__init__(dev, hub_xact_fn)
        self.is_online = None
        self.curl_proc = None

    def work(self):
        dispatch_curl = False
        if self.curl_proc is not None:
            if self.curl_proc.poll() is not None:
                pout = self.curl_proc.communicate()[0].decode('utf-8')
                dispatch_curl = True
                curr_online = (
                    self.curl_proc.returncode == 0 and 'OK' in pout.split('\n', maxsplit=1)[0]
                )
                if self.is_online != curr_online:
                    self.hub_transact('dev_cmd', dev_id=self.dev['id'],
                        cmd=('arrived' if curr_online else 'departed'))
                    logging.info('%s: Online status changed to %s', self.dev["name"], curr_online)
                self.is_online = curr_online
        else:
            dispatch_curl = True
        if dispatch_curl:
            self.curl_proc = subprocess.Popen(['curl', '-m', '5', '-I', 'http://www.example.com'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

class LanMonReader(Worker):
    def __init__(self, dev, hub_xact_fn, ifaces):
        super(LanMonReader, self).__init__(dev, hub_xact_fn)
        self.lanmon = ifaces['lan-monitor']
        self.ip_addr = dev['worker-args']['addr']
        self.is_online = None

    def work(self):
        curr_online = False
        for ip, _, _, _ in self.lanmon.get_active_clients():
            if ip == self.ip_addr:
                curr_online = True
                break
        if self.is_online != curr_online:
            self.hub_transact('dev_cmd', dev_id=self.dev['id'],
                cmd=('arrived' if curr_online else 'departed'))
            logging.info('%s: Online status changed to %s',
                         self.dev["name"], curr_online)
        self.is_online = curr_online

class EventDaemon:
    def __init__(self, cfg_file, poll_interval):
        CFG_FILE_VER = 1
        self.poll_interval = poll_interval
        with open(cfg_file, encoding='utf-8') as json_f:
            print(cfg_file)
            cfg_blob = json.load(json_f)
            print(cfg_blob)
            if cfg_blob['version'] != CFG_FILE_VER:
                raise RuntimeError('Config file has the wrong version')
            url_prefix = f'http://{cfg_blob["hubitat-addr"]}/apps/api/{cfg_blob["maker-api"]["id"]}/devices/'
            url_suffix = f'?access_token={cfg_blob["maker-api"]["token"]}'
            self.url_fns = {
                'ls_dev': lambda: f'{url_prefix}all{url_suffix}',
                'dev_info': lambda dev_id: f'{url_prefix}{dev_id}{url_suffix}',
                'dev_cmd': lambda dev_id, cmd: f'{url_prefix}{dev_id}/{cmd}{url_suffix}',
                'dev_cmd_arg': lambda dev_id, cmd, arg: f'{url_prefix}{dev_id}/{cmd}/{arg}{url_suffix}',
            }
            self.avail_devs = {}
            for dev in self.hub_transact('ls_dev'):
                self.avail_devs[dev['id']] = dev
            self.worker_ifaces = {'lan-monitor': LanMonitor(**cfg_blob['lan-monitor'])}
            self.workers = {}
            for dev in cfg_blob["devices"]:
                dev_id = dev['id']
                logging.info('Adding device %s (ID=%s, Worker=%s, Args=%s)',
                             dev["name"], dev_id, dev["worker"], dev["worker-args"])
                if dev_id not in self.avail_devs:
                    raise RuntimeError('Could not access device through Maker API')
                if dev["poll-interval"] < poll_interval:
                    raise RuntimeError('Poll interval of device is less than that of the daemon')
                self.workers[dev_id] = globals()[dev['worker']](
                    dev, self.hub_transact, self.worker_ifaces
                )

    def hub_transact(self, op, **kwargs):
        url = self.url_fns[op](**kwargs)
        response = requests.get(url, timeout=5)
        return response.json()

    def run(self):
        while True:
            try:
                for worker in self.workers.values():
                    worker.work_if_due()
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logging.info('Stopping event loop...')
                self.worker_ifaces['lan-monitor'].stop()
                logging.info('Event loop terminated')
                return

def main():
    parser = argparse.ArgumentParser(description='Hubitat Event Notifier Daemon')
    parser.add_argument('--cfg-json', type=str, required=True, help='Path to JSON config file')
    parser.add_argument('--poll-interval', type=float, default=5.0, help='Polling interval')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    evnt_dmn = EventDaemon(args.cfg_json, args.poll_interval)
    evnt_dmn.run()

if __name__ == '__main__':
    main()
