#!/usr/bin/env python3

import os, sys
import argparse
import time
import pytz
from datetime import datetime
import re
from influxdb import InfluxDBClient

INFLUXDB_HOST = 'localhost'
INFLUXDB_PORT = 8086
DB_NAME = 'Hubitat'
IGNORE_COLS = ['hubId', 'hubName', 'locationId', 'locationName', 'groupId', 'groupName']
TIME_ATTR = 'time'
DEVICE_ATTR = 'deviceName'

def utc2local(utc):
    epoch = time.mktime(utc.timetuple())
    offset = datetime.fromtimestamp(epoch) - datetime.utcfromtimestamp(epoch)
    return utc + offset

def print_table(row_data, cols = None):
    if not row_data:
        return
    if cols is None:
        cols = list(row_data[0].keys())
    table = [cols]
    for r in row_data:
        table.append([str(r[k]) for k in cols])
    longest_cols = [
        (max([len(str(row[i])) for row in table]) + 1) for i in range(len(table[0]))]
    width = sum(longest_cols) + (len(longest_cols) * 3)
    row_format = "|" + "".join(["{:>" + str(longest_col) + "} | " \
        for longest_col in longest_cols])
    print('-' * width)
    header = True
    for row in table:
        print(row_format.format(*row))
        if header:
            print('-' * width)
            header = False
    print('-' * width)

class SensorDbClient:
    def __init__(self, cred_file):
        with open(cred_file, 'r') as f:
            lines = f.readlines()
        user, passwd = lines[0].strip(), lines[1].strip()
        self.client = InfluxDBClient(INFLUXDB_HOST, INFLUXDB_PORT, user, passwd, DB_NAME)

    def query_raw_sql(self, query):
        return self.client.query(query).get_points()

    def query(self, measurement, 
              t_strt = None, t_stop = datetime.now(), reverse = False, device = '.*'):
        t_strt_unix = int(time.mktime(t_strt.timetuple()) * 1e9) \
            if t_strt is not None else 0
        t_stop_unix = int(time.mktime(t_stop.timetuple()) * 1e9)
        sql = (f'SELECT * FROM "{measurement}" '
               f'WHERE ({TIME_ATTR} >= {t_strt_unix} AND {TIME_ATTR} <= {t_stop_unix}) '
               f'ORDER BY {TIME_ATTR} {("DESC" if reverse else "ASC")}')
        results = []
        for rrow in self.query_raw_sql(sql):
            frow = {}
            if re.search(device, rrow[DEVICE_ATTR]):
                for key in rrow:
                    if key in IGNORE_COLS:
                        continue
                    elif key[-2:] == 'Id':
                        frow[key] = int(rrow[key]) if rrow[key] != 'null' else None
                    elif key == TIME_ATTR:
                        try:
                            frow[key] = utc2local(
                                datetime.strptime(rrow[key], "%Y-%m-%dT%H:%M:%S.%fZ"))
                        except ValueError:
                            frow[key] = utc2local(
                                datetime.strptime(rrow[key], "%Y-%m-%dT%H:%M:%SZ"))
                    else:
                        frow[key] = rrow[key]
                results.append(frow)
        return results

class SensorHist:
    def __init__(self, db_client, meas, dev_name, t_strt, t_stop):
        self.db_client = db_client
        self.meas = meas
        self.dev_name = dev_name
        self.values = []
        self.val_map = {}
        data = self.db_client.query(
            meas, t_strt=t_strt, t_stop=t_stop, reverse=False, device=dev_name)
        value_attr = None
        for rec in data:
            if rec[DEVICE_ATTR].strip() != self.dev_name.strip():
                raise ValueError(f'Device name does not match record')
            if value_attr is None:
                value_attr = 'valueBinary' if 'valueBinary' in rec else 'value'
            self.values.append((rec[TIME_ATTR], rec[value_attr]))
            if value_attr == 'valueBinary':
                self.val_map[rec[value_attr]] = rec['value']

    def val2str(self, val):
        if val in self.val_map:
            return self.val_map[val]
        else:
            return str(val)

    def calc_stats(self):
        pts = [v[1] for v in self.values]
        stats = {'num': len(pts)}
        if stats['num'] > 0:
            try:
                stats['min'] = min(pts)
                stats['max'] = max(pts)
                stats['mean'] = sum(pts) / len(pts)
            except TypeError:
                return {'num': len(pts)}
        return stats

    def calc_transitions(self):
        last_val = None
        transitions = []
        for ts, val in self.values:
            if last_val is not None:
                if val != last_val:
                    try:
                        transitions.append((ts, val - last_val))
                    except TypeError:
                        transitions.append((ts, f'{last_val} -> {val}'))
            last_val = val
        return transitions


def main():
    parser = argparse.ArgumentParser(description='Hubitat Sensor Influx Database Client')
    parser.add_argument('--creds', type=str, required=True, help='Path to credentials file')
    parser.add_argument('--meas', type=str, required=True, help='Measurement to query (table name)')
    parser.add_argument('--rev', action='store_true', help='Display results in reverse cron order')
    parser.add_argument('--dev', type=str, default='.*', help='Device name to filter by')
    parser.add_argument('--start', type=str, default=None, help='Start timestamp (%Y-%m-%d %H:%M:%S)')
    parser.add_argument('--stop', type=str, default=None, help='Stop timestamp (%Y-%m-%d %H:%M:%S)')
    args = parser.parse_args()

    client = SensorDbClient(args.creds)
    query = {"reverse": args.rev, "device": args.dev}
    query["t_strt"] = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S") if args.start else None
    query["t_stop"] = datetime.strptime(args.stop, "%Y-%m-%d %H:%M:%S") if args.stop else datetime.now()

    print_table(client.query(args.meas, **query))
    sens = SensorHist(client, args.meas, query['device'], query["t_strt"], query["t_stop"])
    print(sens.calc_stats())
    print(sens.calc_transitions())

if __name__ == "__main__":
    main()