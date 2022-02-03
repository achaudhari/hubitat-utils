#!/usr/bin/env python3

import os, sys
import datetime
import argparse
import pickle
import re
import glob
from common import EmailUtils

def discover_new_files(base_dir):
    pickle_fname = os.path.join(base_dir, 'snapshot.pickle')
    prev_st = set()
    if os.path.isfile(pickle_fname):
        with open(pickle_fname, 'rb') as pickle_f:
            prev_st = pickle.load(pickle_f)
    curr_st = set()
    for fpath in os.listdir(base_dir):
        fpath = os.path.join(base_dir, fpath)
        if os.path.isfile(fpath) and fpath != pickle_fname:
            curr_st.add(fpath)
    with open(pickle_fname, 'wb') as pickle_f:
        pickle.dump(curr_st, pickle_f)
    if prev_st is not None:
        return list(curr_st - prev_st)
    else:
        return None

def poll(base_dir, cam_name, email_addr, verbose):
    if verbose:
        print(f'[DEBUG] Polling started at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    processed = 0
    for jpeg_f in discover_new_files(base_dir):
        if verbose:
            print(f'[DEBUG] Found new file: {jpeg_f}')
        match = re.match('(.+)-(.+)-e(.+)-f(.+).jpg', os.path.basename(jpeg_f))
        if match:
            if verbose:
                print(f'[DEBUG] Found new summary image: {jpeg_f}')
            mp4_pat = f'*-*-e{match.group(3)}.mp4'
            mp4_f = glob.glob(os.path.join(base_dir, mp4_pat))
            if mp4_f:
                if verbose:
                    print(f'[DEBUG] Matched a video: {mp4_f}')
                mp4_f = mp4_f[0]
                subject = f'Your {cam_name} camera detected motion'
                email_html = '<html><body><img src="cid:motion_snapshot"/></body></html>'
                inline_images = {'motion_snapshot': jpeg_f}
                attachments = [mp4_f]
                EmailUtils.send_email_html(
                    email_addr, subject, email_html, inline_images, attachments)
                if verbose:
                    print(f'[DEBUG] Sent email to {email_addr}')
                processed += 1
    if verbose:
        print(f'[DEBUG] Polling ended at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}:'
              f' {processed} changes')
    return processed

def main():
    parser = argparse.ArgumentParser(description='Hubitat Offload Daemon')
    parser.add_argument('--dir', '-d', type=str, required=True, help='Directory to poll')
    parser.add_argument('--name', '-n', type=str, required=True, help='Camera name')
    parser.add_argument('--email', '-e', type=str, required=True, help='Email to notify')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()
    sys.exit(poll(os.path.abspath(args.dir), args.name, args.email, args.verbose))

if __name__ == '__main__':
    main()
