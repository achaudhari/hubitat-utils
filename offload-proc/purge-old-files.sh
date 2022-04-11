#!/bin/bash

if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ]; then
    echo "Usage: $0 CMD LOCATION PATTERN AGE"
    echo "- CMD must be -f (force) or -n (dry-run)"
    exit
fi
CMD=$1
LOCATION=$2
PATTERN=$3
AGE=$4

if [[ "$CMD" == "-n" ]]; then
    echo "INFO: Would delete files older than $AGE days that match pattern $PATTERN in $LOCATION"
    find ${LOCATION}/${PATTERN} -mtime +${AGE} -exec echo "x {}" \;
elif [[ "$CMD" == "-f" ]]; then
    echo "INFO: Deleting files older than $AGE days that match pattern $PATTERN in $LOCATION"
    find ${LOCATION}/${PATTERN} -mtime +${AGE} -exec echo "x {}" \; -exec rm -f {} \;
else
    echo "ERROR: Invalid cmd: $CMD"
fi