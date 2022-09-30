#!/bin/bash

cred_file=/home/admin/cfg/hubitat.creds
enc_pass=$(cat /sys/class/net/eth0/address)

echo -n "Hub Login: "
read he_login
echo -n "Password: "
read -s he_passwd
echo ""

echo ${he_login} | openssl enc -e -des3 -base64 -pass pass:${enc_pass} -pbkdf2 > ${cred_file}
echo ${he_passwd} | openssl enc -e -des3 -base64 -pass pass:${enc_pass} -pbkdf2 >> ${cred_file}

echo "INFO: Wrote ${cred_file}"