#!/bin/bash

if [[ "$1" == "" ]]; then
    echo "ERROR: Usage $0 <action>"
    exit 2
fi

he_ipaddr=192.168.1.192
cred_file=/home/admin/cfg/hubitat.creds
cookie_file=/home/admin/cfg/hubitat.cookie
enc_pass=$(cat /sys/class/net/eth0/address)

cat ${cred_file} | {
    read -r he_login_ct;
    read -r he_passwd_ct;
    he_login=$(echo ${he_login_ct} | openssl enc -d -des3 -base64 -pass pass:${enc_pass} -pbkdf2)
    he_passwd=$(echo ${he_passwd_ct} | openssl enc -d -des3 -base64 -pass pass:${enc_pass} -pbkdf2)
    curl -k -c $cookie_file -d username=$he_login -d password=$he_passwd https://$he_ipaddr/login
    echo "INFO: Saved Hubitat cookie $cookie_file"
}

if [[ "$1" == "reboot" ]]; then
    echo "INFO: Rebooting from Hubitat hub"
    curl -k -sb $cookie_file -X POST https://${he_ipaddr}/hub/reboot
elif [[ "$1" == "shutdown" ]]; then
    echo "INFO: Shutting down Hubitat hub"
    curl -k -sb $cookie_file -X POST https://${he_ipaddr}/hub/shutdown
elif [[ "$1" == "backup" ]]; then
    if [[ "$2" == "" ]]; then
        echo "ERROR: Usage $0 backup <save path>"
        exit 2
    fi
    backupdir=$2
    echo "INFO: Downloading backup from Hubitat hub"
    backupfile=$backupdir/hub_backup_$(date +%Y-%m-%d_%H%M).lzf
    curl -k -sb $cookie_file https://$he_ipaddr/hub/backupDB?fileName=latest -o $backupfile
    echo "INFO: Saved $backupfile"
else 
    echo "ERROR: Invalid action: $1 (must be backup or cookie)"
    exit 1
fi