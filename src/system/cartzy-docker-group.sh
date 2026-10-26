#!/bin/sh
# Add cartzy user to docker group (runs after cartzy-firstboot.sh)
set -e

if id cartzy >/dev/null 2>&1; then
    usermod -aG docker cartzy
fi
