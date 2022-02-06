#!/usr/bin/env python3

import os

DEV_ROOT = '/sys/devices/virtual/thermal/thermal_zone0'

def get_temp(which):
    with open(os.path.join(DEV_ROOT, which), 'r') as f:
        return int(f.readline()) / 1000.0

def main():
    print(f'Temperature : {get_temp("temp"):6.02f} deg C')
    print(f'Warning     : {get_temp("trip_point_0_temp"):6.02f} deg C')
    print(f'Critical    : {get_temp("trip_point_3_temp"):6.02f} deg C')

if __name__ == "__main__":
    main()