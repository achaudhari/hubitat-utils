#!/bin/bash

BACKUP_LOC=${1:-"/home/admin/backup"}
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

cd /home/admin
backupfile=$(date +%Y-%m-%d_%H%M).tar.gz
echo "Creating cfg backup file $backupfile"
mkdir -p ${BACKUP_LOC}/cfg
tar -czf ${BACKUP_LOC}/cfg/$(date +%Y-%m-%d_%H%M).tar.gz cfg
echo "Creating www backup file $backupfile"
mkdir -p ${BACKUP_LOC}/www
tar -czf ${BACKUP_LOC}/www/$(date +%Y-%m-%d_%H%M).tar.gz www
${SCRIPT_DIR}/download-hubitat-backup.sh backup ${BACKUP_LOC}/hubitat
