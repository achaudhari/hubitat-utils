#!/usr/bin/env python3
import copy
from datetime import datetime, timedelta
import ipaddress
import threading
import traceback
import subprocess
import re
import time
import fcntl
import pickle
import dominate
from dominate.tags import *

from common import MacAddrDb
from common import EmailUtils

class RouterIfc:
    def __init__(self, ssh_addr, ssh_port, ssh_user, mac_tbl_dir):
        ssh_opts = "-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        self.arp_cmd = f'ssh {ssh_opts} {ssh_user}@{ssh_addr} -p {ssh_port} arp -a 2>/dev/null'
        self.ip_neigh_cmd = f'ssh {ssh_opts} {ssh_user}@{ssh_addr} -p {ssh_port} ip neigh 2>/dev/null'
        subprocess.check_output(self.ip_neigh_cmd, shell=True)
        self.mac_db = MacAddrDb(mac_tbl_dir)

    def _read_ip_neigh(self, max_retries = 3):
        neigh_cache = {}
        for i in range(max_retries):
            try:
                ip_neigh_out = subprocess.check_output(self.ip_neigh_cmd, shell=True).decode('utf-8')
                for line in ip_neigh_out.split('\n'):
                    toks = [x.strip() for x in line.split()]
                    if len(toks) > 0:
                        state = toks[-1]
                        if len(toks) == 6:
                            ip, mac = toks[0], toks[4]
                        else:
                            ip, mac = None, None
                        neigh_cache[ip] = (mac, state)
                failed_cnt = len([st for _, (_, st) in neigh_cache.items() if st in ['FAILED', 'INCOMPLETE']])
            except Exception:
                failed_cnt = 1000

            if failed_cnt == 0:
                break
            if i == max_retries - 1:
                time.sleep(0.25)
        retval = []
        for ip, (mac, state) in neigh_cache.items():
            if state not in ['FAILED', 'INCOMPLETE']:
                retval.append((ip, mac, self.mac_db.get_vendor(mac, 'Unknown')))
        return sorted(retval, key = lambda x: ipaddress.IPv4Address(x[0]))

    def _read_arp_tbl(self):
        arp_out = subprocess.check_output(self.arp_cmd, shell=True).decode('utf-8')
        arp_tbl = {}
        for line in arp_out.split('\n'):
            m = re.match(r'(.+)\s+\((.+)\)\s+at.*', line)
            if m is not None:
                arp_tbl[m.group(2)] = m.group(1)
        return arp_tbl

    def get_active_clients(self):
        arp_tbl = self._read_arp_tbl()
        all_clients = []
        for ip, mac, vendor in self._read_ip_neigh():
            if ip in arp_tbl:
                client_name = arp_tbl[ip].lower()
                if client_name == '?':
                    client_name = 'Unknown'
                elif client_name[-1] == '.':
                    client_name += 'local'
            else:
                client_name = 'Unknown'
            all_clients.append((ip, mac, vendor, client_name))
        return all_clients

class LanMonitor:
    QUIESCE_HOURS = 24

    def __init__(self, rtr_ssh_addr, rtr_ssh_port, rtr_ssh_user, mac_tbl_dir, poll_interval,
                 known_mac_addrs = [],
                 notification_email_to = None, notification_email_from = None,
                 pickle_dump_fname = None):
        self.rtr_ifc = RouterIfc(rtr_ssh_addr, rtr_ssh_port, rtr_ssh_user, mac_tbl_dir)
        self.interval = poll_interval
        self.known_mac_addrs = set([x.split()[0].lower() for x in known_mac_addrs])
        self.mac_aliases = {x.split()[0].lower(): ' '.join(x.split()[1:]) for x in known_mac_addrs}
        self.notification_email_to = notification_email_to
        self.notification_email_from = notification_email_from
        self.pickle_dump_fname = pickle_dump_fname
        self.curr_clients = self.rtr_ifc.get_active_clients()
        self.last_clients = copy.deepcopy(self.curr_clients)
        self.quiesce_tbl = {}
        self.stop_thread = False
        self.monitor_error = None
        self.lock = threading.Lock()
        self.mon_thread = threading.Thread(target=self._monitor_loop)
        self.mon_thread.start()

    def _monitor_loop(self):
        try:
            while not self.stop_thread:
                next_t = datetime.today() + timedelta(seconds=self.interval)
                with self.lock:
                    self.curr_clients = []
                    for ip, mac, vendor, name in self.rtr_ifc.get_active_clients():
                        known_alias = self.mac_aliases[mac] if mac in self.mac_aliases else ''
                        if name == 'Unknown' and known_alias:
                            name = f'Known ({known_alias})'
                        self.curr_clients.append((ip, mac, vendor, name))
                self._handle_new_client_notifications()
                if self.pickle_dump_fname:
                    with open(self.pickle_dump_fname, 'wb') as pickle_f:
                        pickle_ds = {
                            'timestamp': datetime.today(),
                            'clients': self.curr_clients
                        }
                        fcntl.flock(pickle_f.fileno(), fcntl.LOCK_EX)
                        pickle.dump(pickle_ds, pickle_f, protocol=pickle.HIGHEST_PROTOCOL)
                        fcntl.flock(pickle_f.fileno(), fcntl.LOCK_UN)
                sleep_sec = (next_t - datetime.today()).total_seconds()
                if sleep_sec > 0.0:
                    time.sleep(sleep_sec)
        except Exception:
            with self.lock:
                self.monitor_error = traceback.format_exc()

    def _handle_new_client_notifications(self):
        last_macs = set([t[1] for t in self.last_clients]) - self.known_mac_addrs
        curr_macs = set([t[1] for t in self.curr_clients]) - self.known_mac_addrs
        if last_macs != curr_macs:
            new_client_idxs = []
            for idx, (ip, mac, vendor, client_name) in enumerate(self.curr_clients):
                if mac in curr_macs and mac not in last_macs and mac not in self.quiesce_tbl:
                    new_client_idxs.append(idx)
                    self.quiesce_tbl[mac] = datetime.today() + timedelta(hours=LanMonitor.QUIESCE_HOURS)
            new_clients = [self.curr_clients[i] for i in new_client_idxs]
            if new_clients and self.notification_email_to:
                self._send_notification(new_clients)
        for qmac in list(self.quiesce_tbl.keys()):
            if self.quiesce_tbl[qmac] < datetime.today():
                del self.quiesce_tbl[qmac]
        self.last_clients = copy.deepcopy(self.curr_clients)

    def _send_notification(self, new_clients):
        title = 'LAN Monitor Notification'
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
            p(f'{datetime.now().strftime("%Y-%m-%d %l:%M:%S %p")}', style="font-weight: bold; color:blue")
            p(f'One or more new devices have connected to the Home LAN')
            tbl_def = [('New Clients', new_clients), ('All Clients', self.curr_clients)]
            for tname, tdata in tbl_def:
                with h3():
                    u(tname)
                with table().add(tbody()):
                    with tr():
                        for hdr in ['IP Address', 'MAC Address', 'Vendor', 'Name']:
                            td(hdr, style='font-weight: bold;')
                    for nrow, trow in enumerate(tdata):
                        with tr():
                            for tcell in trow:
                                td(tcell)
        subject = f'INFO: LAN Monitor Notification ({datetime.now().strftime("%Y-%m-%d")})'
        EmailUtils.send_email_html(
            self.notification_email_from,
            self.notification_email_to,
            subject, str(doc))

    def stop(self):
        self.stop_thread = True
        self.mon_thread.join()

    def get_active_clients(self):
        with self.lock:
            if self.monitor_error:
                raise RuntimeError(f'LanMonitor error: {self.monitor_error}')
            return copy.deepcopy(self.curr_clients)
