#!/usr/bin/env python3
import logging
import json
import argparse
import requests
import netifaces
import re
from nmap import PortScanner

class NetIfcInfo:
    def __init__(self):
        # Pick a gateway
        for gw in netifaces.gateways()["default"].values():
            self.gw_ip_addr, self.gw_ifc = gw
        addrs = netifaces.ifaddresses(self.gw_ifc)
        # Interface IP address
        af_inet = addrs[netifaces.AF_INET][0]
        self.ifc_ip_addr = af_inet['addr']
        self.ifc_netmask = af_inet['netmask']
        self.ifc_bcast = af_inet['broadcast']
        self.ifc_netmask_w = sum(
            bin(int(x)).count('1') for x in self.ifc_netmask.split('.'))
        # Interface MAC address
        self.ifc_mac = addrs[netifaces.AF_LINK][0]['addr']


class IeeeOuiTbl:
    OUI_TXT_URL = 'http://standards.ieee.org/develop/regauth/oui/oui.txt'

    def __init__(self):
        url_resp = requests.get(IeeeOuiTbl.OUI_TXT_URL)
        if not url_resp.ok:
            raise RuntimeError('Could not build OUI table. URL get failed: ' + 
                               IeeeOuiTbl.OUI_TXT_URL)
        self.oui_tbl = {}
        for line in url_resp.text.split('\n'):
            try:
                mac, company = re.search(
                    r'([0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2})\s+\(hex\)\s+(.+)',
                line).groups()
                self.oui_tbl[mac.replace('-', ':')] = company
            except AttributeError:
                continue

    def dump(self):
        for mac in sorted(self.oui_tbl):
            print(f'{mac} = {self.oui_tbl[mac]}')

    def lookup(self, mac):
        return self.oui_tbl[mac.upper()[0:8]]

class Scanner:
    def __init__(self, net_ifc, oui_tbl = None):
        self.self_ip = net_ifc.ifc_ip_addr
        self.scan_ip = f'{net_ifc.ifc_bcast}/{net_ifc.ifc_netmask_w}'
        self.oui_tbl = oui_tbl

    def get_devices(self):
        nmap_inst = PortScanner()
        nmap_inst.scan(hosts=self.scan_ip, arguments='-sn')
        for ip in sorted(nmap_inst.all_hosts()):
            if ip == self.self_ip:
                continue
            info = nmap_inst[ip]
            hostname = '<Unknown>'
            for hrec in info['hostnames']:
                if hrec['name']:
                    hostname = hrec['name']
                    break
            mac = '<Unknown>'
            vendor = '<Unknown>'
            if 'mac' in info['addresses']:
                mac = info['addresses']['mac']
                if self.oui_tbl:
                    try:
                        vendor = self.oui_tbl.lookup(mac)
                    except LookupError:
                        pass
            print(ip, hostname, mac, vendor)
        return len(nmap_inst.all_hosts())


def main():
    parser = argparse.ArgumentParser(description='Hubitat Event Notifier Daemon')
    parser.add_argument('--cfg-json', type=str, default=None, help='Path to JSON config file')
    parser.add_argument('--poll-interval', type=float, default=10.0, help='Polling interval')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    logging.info('Querying local network interfaces')
    net_ifc = NetIfcInfo()

    logging.info('Getting most recent OUI table from IEEE')
    oui_tbl = IeeeOuiTbl()

    scanner = Scanner(net_ifc, oui_tbl)
    print(scanner.get_devices())

if __name__ == '__main__':
    main()
