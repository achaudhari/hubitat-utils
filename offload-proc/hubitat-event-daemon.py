#!/usr/bin/env python3
import subprocess
import time
import logging
import json
import argparse
import requests
import random

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
            logging.debug(f'{self.dev["name"]}: {self.dev["worker"]}::work() '
                          f'finished in {(time.time()-time_now):03f}s')
    def hub_transact(self, *args, **kwargs):
        return self._hub_xact_fn(*args, **kwargs)

class Pinger(Worker):
    def __init__(self, dev, hub_xact_fn):
        super(Pinger, self).__init__(dev, hub_xact_fn)
        self.ip_addr = dev['worker-args']['addr']
        self.is_online = False
        self.ping_proc = None

    def work(self):
        dispatch_ping = False
        if self.ping_proc is not None:
            if self.ping_proc.poll() is not None:
                self.ping_proc.communicate()
                dispatch_ping = True
                curr_online = (self.ping_proc.returncode == 0)
                if self.is_online != curr_online:
                    self.hub_transact('dev_cmd', dev_id=self.dev['id'],
                        cmd=('arrived' if curr_online else 'departed'))
                    logging.info(f'{self.dev["name"]}: Online status changed to {curr_online}')
                self.is_online = curr_online
        else:
            dispatch_ping = True
        if dispatch_ping:
            self.ping_proc = subprocess.Popen(['ping', self.ip_addr, '-i', '0.5', '-c', '4'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

class InternetChecker(Worker):
    def __init__(self, dev, hub_xact_fn):
        super(InternetChecker, self).__init__(dev, hub_xact_fn)
        self.is_online = False
        self.curl_proc = None

    def work(self):
        dispatch_curl = False
        if self.curl_proc is not None:
            if self.curl_proc.poll() is not None:
                self.curl_proc.communicate()
                dispatch_curl = True
                curr_online = (self.curl_proc.returncode == 0)
                if self.is_online != curr_online:
                    self.hub_transact('dev_cmd', dev_id=self.dev['id'],
                        cmd=('arrived' if curr_online else 'departed'))
                    logging.info(f'{self.dev["name"]}: Online status changed to {curr_online}')
                self.is_online = curr_online
        else:
            dispatch_curl = True
        if dispatch_curl:
            self.curl_proc = subprocess.Popen(['curl', '-m', '5', '-I', 'http://www.google.com'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

class MotionPoll(Worker):
    def __init__(self, dev, hub_xact_fn):
        super(MotionPoll, self).__init__(dev, hub_xact_fn)
        self.curl_proc = None

    def work(self):
        dispatch_poll = False
        if self.curl_proc is not None:
            if self.curl_proc.poll() is not None:
                self.curl_proc.communicate()
                dispatch_poll = True
                if self.curl_proc.returncode > 0:
                    self.hub_transact('dev_cmd', dev_id=self.dev['id'], cmd='active')
                    logging.info(f'{self.dev["name"]}: Motion detected')
        else:
            dispatch_poll = True
        if dispatch_poll:
            self.curl_proc = subprocess.Popen(['python3', '/usr/local/bin/motion-poll.py',
                '-d', self.dev['worker-args']['dir'], '-e', self.dev['worker-args']['email'],
                '-n', self.dev["name"]],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

class EventDaemon:
    def __init__(self, cfg_file, poll_interval):
        CFG_FILE_VER = 1
        self.poll_interval = poll_interval
        with open(cfg_file) as json_f:
            cfg_blob = json.load(json_f)
            if cfg_blob['version'] != CFG_FILE_VER:
                raise RuntimeError(f'Config file has the wrong version')
            url_prefix = f'http://{cfg_blob["hubitat-addr"]}/apps/api/{cfg_blob["maker-api"]["id"]}/devices/'
            url_suffix = f'?access_token={cfg_blob["maker-api"]["token"]}'
            self.url_fns = {
                'ls_dev': lambda: f'{url_prefix}all{url_suffix}',
                'dev_info': lambda dev_id: f'{url_prefix}{dev_id}{url_suffix}',
                'dev_cmd': lambda dev_id, cmd: f'{url_prefix}{dev_id}/{cmd}{url_suffix}',
                'dev_cmd_arg': lambda dev_id, cmd, arg: f'{url_prefix}{dev_id}/{cmd}/{val}{url_suffix}',
            }
            self.avail_devs = {}
            for dev in self.hub_transact('ls_dev'):
                self.avail_devs[dev['id']] = dev
            self.workers = {}
            for dev in cfg_blob["devices"]:
                dev_id = dev['id']
                logging.info(f'Adding device {dev["name"]} '
                             f'(ID={dev_id}, Worker={dev["worker"]}, Args={dev["worker-args"]})')
                if dev_id not in self.avail_devs:
                    raise RuntimeError(f'Could not access device through Maker API')
                if dev["poll-interval"] < poll_interval:
                    raise RuntimeError(f'Poll interval of device is less than that of the daemon')
                self.workers[dev_id] = globals()[dev['worker']](dev, self.hub_transact)

    def hub_transact(self, op, **kwargs):
        url = self.url_fns[op](**kwargs)
        response = requests.get(url)
        return response.json()

    def run(self):
        while True:
            try:
                for dev_id, worker in self.workers.items():
                    worker.work_if_due()
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logging.info('Event loop terminated')
                return

def main():
    parser = argparse.ArgumentParser(description='Hubitat Offload Daemon')
    parser.add_argument('--cfg-json', type=str, default=None, help='Path to JSON config file')
    parser.add_argument('--poll-interval', type=float, default=10.0, help='Polling interval')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    evnt_dmn = EventDaemon(args.cfg_json, args.poll_interval)
    evnt_dmn.run()

if __name__ == '__main__':
    main()
