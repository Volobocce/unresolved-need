#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/home/ubuntu/GBI_103_H200_CPA_001_GITHUB_RUN
rm -rf "$ROOT"
git clone --depth 1 https://github.com/Volobocce/unresolved-need.git "$ROOT"
cd "$ROOT/cpa001"
chmod +x RUN_CPA_001.sh verify_package.sh run_h200.sh
exec ./RUN_CPA_001.sh
