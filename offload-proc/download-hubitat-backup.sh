#!/bin/bash

backupdir=$2
he_ipaddr=192.168.1.192
cookiefile=${backupdir}/hubitat.cookie

if [[ "$2" == "" ]]; then
    echo "ERROR: Usage $0 <action> <save path>"
    exit 2
fi

if [[ "$1" == "cookie" ]]; then
    echo -n "Hub Login: "
    read he_login
    echo -n "Password: "
    read -s he_passwd
    echo ""
    curl -k -c $cookiefile -d username=$he_login -d password=$he_passwd https://$he_ipaddr/login
    echo "Saved $cookiefile"
elif [[ "$1" == "backup" ]]; then
    echo "INFO: Downloading backup from Hubitat hub"
    backupfile=$backupdir/hub_backup_$(date +%Y-%m-%d_%H%M).lzf
    curl -k -sb $cookiefile https://$he_ipaddr/hub/backupDB?fileName=latest -o $backupfile
    echo "INFO: Saved $backupfile"
elif [[ "$1" == "" ]]; then
    echo "ERROR: Usage $0 <action> <save path>"
    exit 1
else 
    echo "ERROR: Invalid action: $1 (must be backup or cookie)"
    exit 1
fi