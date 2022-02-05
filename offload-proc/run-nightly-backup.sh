#!/bin/bash

BACKUP_LOC=${1:-"/home/admin/backup"}

cd /home/admin
backupfile=$(date +%Y-%m-%d_%H%M).tar.gz
echo "Creating cfg backup file $backupfile"
mkdir -p ${BACKUP_LOC}/cfg
tar -czf ${BACKUP_LOC}/cfg/$(date +%Y-%m-%d_%H%M).tar.gz cfg
echo "Creating www backup file $backupfile"
mkdir -p ${BACKUP_LOC}/www
tar -czf ${BACKUP_LOC}/www/$(date +%Y-%m-%d_%H%M).tar.gz www
/home/admin/backup/create-hubitat-backup.sh backup ${BACKUP_LOC}/hubitat
