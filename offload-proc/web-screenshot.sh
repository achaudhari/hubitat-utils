#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

export LIBGL_ALWAYS_SOFTWARE=true
export QT_XCB_GL_INTEGRATION=none
xvfb-run -a python3 ${SCRIPT_DIR}/web-screenshot.py $@