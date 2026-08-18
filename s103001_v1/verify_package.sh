#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
sha256sum -c PACKAGE_SHA256SUMS.txt
echo 'PACKAGE VERIFY PASS'
