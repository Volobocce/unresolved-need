#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/home/ubuntu/GBI_103_H200_S103_001_GITHUB_RUN
cd /home/ubuntu
rm -rf "$ROOT"
git clone --depth 1 https://github.com/Volobocce/unresolved-need.git "$ROOT"
cd "$ROOT/s103001_v1"
chmod +x RUN_S103_001.sh verify_package.sh run_h200.sh
exec ./RUN_S103_001.sh
