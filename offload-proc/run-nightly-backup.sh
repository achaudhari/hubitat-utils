#!/bin/bash

BACKUP_LOC=${1:-"/home/admin/backup"}
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

MAX_DAYS=60

cd /home/admin
backupfile=$(date +%Y-%m-%d_%H%M).tar.gz

echo "INFO: Creating cfg backup file $backupfile"
mkdir -p ${BACKUP_LOC}/cfg
tar -czf ${BACKUP_LOC}/cfg/$backupfile cfg
${SCRIPT_DIR}/purge-old-files.sh -f ${BACKUP_LOC}/cfg '*.tar.gz' $MAX_DAYS

echo "INFO: Creating www backup file $backupfile"
mkdir -p ${BACKUP_LOC}/www
tar -czf ${BACKUP_LOC}/www/$backupfile www
${SCRIPT_DIR}/purge-old-files.sh -f ${BACKUP_LOC}/www '*.tar.gz' $MAX_DAYS

${SCRIPT_DIR}/hubitat-admin-ctrl.sh backup ${BACKUP_LOC}/hubitat
${SCRIPT_DIR}/purge-old-files.sh -f ${BACKUP_LOC}/hubitat 'hub_backup_*.lzf' $MAX_DAYS
