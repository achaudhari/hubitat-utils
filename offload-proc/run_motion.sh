#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

for conf_file in /etc/motion/motion-*.conf; do
    echo "INFO: Found camera config: $conf_file"
    IFS=' ' target_dir_tok=( $(cat ${conf_file} | grep target_dir | grep -v "#") )
    CAM_DATA_DIR=${target_dir_tok[1]}
    if [[ "${CAM_DATA_DIR}" == "" ]]; then
        echo "ERROR: Could not find target_dir in ${conf_file}"
    fi
    echo "INFO: Archiving and cleaning up old recordings in ${CAM_DATA_DIR}"
    mkdir -p ${CAM_DATA_DIR}/archive
    mv -f ${CAM_DATA_DIR}/*.mp4 ${CAM_DATA_DIR}/archive >/dev/null 2>&1
    mv -f ${CAM_DATA_DIR}/*.jpg ${CAM_DATA_DIR}/archive >/dev/null 2>&1
    ${SCRIPT_DIR}/purge-old-files.sh -f ${CAM_DATA_DIR}/archive '*.*' 60
done
echo "INFO: Starting motion"
exec /usr/bin/motion
