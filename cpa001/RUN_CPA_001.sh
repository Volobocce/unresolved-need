#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
CAMPAIGN="GBI-103-H200-CPA-001"
EXPECTED_GPU="H200"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu130}"
BOOTSTRAP_LOG="$ROOT/CPA_001_BOOTSTRAP_LAST.log"
: > "$BOOTSTRAP_LOG"
exec > >(tee -a "$BOOTSTRAP_LOG") 2>&1

fail() {
  local msg="$1"
  echo
  echo "============================================================"
  echo "$CAMPAIGN — FAIL-CLOSED"
  echo "============================================================"
  echo "$msg"
  echo "No canonical PASS is asserted. Inspect: $BOOTSTRAP_LOG"
  exit 1
}

banner() {
  echo
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

trap 'rc=$?; if [[ $rc -ne 0 ]]; then echo; echo "FAIL-CLOSED: launcher stopped at line $LINENO (exit $rc)."; fi' EXIT

banner "0/8 PACKAGE INTEGRITY"
chmod +x verify_package.sh run_h200.sh RUN_CPA_001.sh
./verify_package.sh || fail "Frozen package checksum verification failed."

banner "1/8 H200 PREFLIGHT"
command -v nvidia-smi >/dev/null 2>&1 || fail "nvidia-smi is unavailable."
GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1 | tr -d '\r')"
echo "GPU: $GPU_NAME"
[[ "$GPU_NAME" == *"$EXPECTED_GPU"* ]] || fail "Required NVIDIA H200; found: $GPU_NAME"

command -v python3 >/dev/null 2>&1 || fail "python3 is unavailable."
echo "Python: $(python3 --version 2>&1)"

banner "2/8 PYTORCH/CUDA RUNTIME"
if ! python3 - <<'PY' >/dev/null 2>&1
import torch
assert torch.cuda.is_available()
assert "H200" in torch.cuda.get_device_name(0)
PY
then
  echo "PyTorch CUDA/H200 runtime is not ready; repairing automatically."
  if ! python3 -m pip --version >/dev/null 2>&1; then
    python3 -m ensurepip --upgrade || fail "Python pip bootstrap failed."
  fi
  python3 -m pip install --upgrade pip || fail "pip upgrade failed."
  python3 -m pip install torch --index-url "$TORCH_INDEX_URL" || fail "PyTorch CUDA 13 installation failed."
fi

python3 - <<'PY' || fail "PyTorch installed but live CUDA/H200 validation failed."
import torch
print("torch_version =", torch.__version__)
print("cuda_build =", torch.version.cuda)
print("cuda_available =", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit(2)
print("gpu =", torch.cuda.get_device_name(0))
print("capability =", torch.cuda.get_device_capability(0))
if "H200" not in torch.cuda.get_device_name(0):
    raise SystemExit(3)
PY

banner "3/8 SMOKE GATE"
SMOKE_OUT="CPA_001_SMOKE_$(date -u +%Y%m%dT%H%M%SZ)"
./run_h200.sh --smoke --out "$SMOKE_OUT" || fail "Smoke execution failed."
python3 - "$SMOKE_OUT" <<'PY' || exit 1
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])/'VALIDITY.json'
d=json.loads(p.read_text())
print("Smoke validity:", d.get('status'))
if d.get('status') != 'PASS':
    raise SystemExit(1)
PY

banner "4/8 CANONICAL 1M × 5 × DEPTHS 1/2/4/8 RUN"
RUNSTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULT_DIR="GBI_103_H200_CPA_001_${RUNSTAMP}"
./run_h200.sh --out "$RESULT_DIR" || fail "Canonical CPA-001 execution failed."

banner "5/8 EVIDENCE VERIFICATION"
python3 - "$RESULT_DIR" <<'PY' || exit 1
import hashlib, json, pathlib, sys
r=pathlib.Path(sys.argv[1])
valid=json.loads((r/'VALIDITY.json').read_text())
if valid.get('status') != 'PASS':
    raise SystemExit('VALIDITY.json is not PASS')
manifest=json.loads((r/'SHA256SUMS.json').read_text())
for name, rec in manifest.items():
    p=r/name
    if not p.is_file():
        raise SystemExit(f'Missing evidence file: {name}')
    h=hashlib.sha256(p.read_bytes()).hexdigest()
    if h != rec['sha256']:
        raise SystemExit(f'Checksum mismatch: {name}')
print(f'EVIDENCE FILE VERIFICATION PASS ({len(manifest)} files)')
PY

cp PACKAGE_SHA256SUMS.txt "$RESULT_DIR/HARNESS_PACKAGE_SHA256SUMS.txt"
cp PREREGISTRATION.json "$RESULT_DIR/HARNESS_PREREGISTRATION.json"
cp IMPLEMENTATION_MAPPING.json "$RESULT_DIR/HARNESS_IMPLEMENTATION_MAPPING.json"
cp SOURCE_PROVENANCE.json "$RESULT_DIR/HARNESS_SOURCE_PROVENANCE.json"
cp INTERPRETATION_LIMITS.txt "$RESULT_DIR/HARNESS_INTERPRETATION_LIMITS.txt"
cp src/cpa_battery.py "$RESULT_DIR/HARNESS_cpa_battery.py"
cp RUN_CPA_001.sh "$RESULT_DIR/HARNESS_RUN_CPA_001.sh"

python3 - "$RESULT_DIR" <<'PY'
import hashlib, json, pathlib, sys
r=pathlib.Path(sys.argv[1])
m={}
for p in sorted(r.iterdir()):
    if p.is_file() and p.name != 'SHA256SUMS.json':
        h=hashlib.sha256()
        with p.open('rb') as f:
            for b in iter(lambda:f.read(1<<20), b''):
                h.update(b)
        m[p.name]={'sha256':h.hexdigest(),'bytes':p.stat().st_size}
(r/'SHA256SUMS.json').write_text(json.dumps(m,indent=2)+"\n")
print(f'Final evidence manifest written: {len(m)} files')
PY

banner "6/8 READ-ONLY EVIDENCE FREEZE"
chmod -R a-w "$RESULT_DIR"
ARCHIVE="${RESULT_DIR}_EVIDENCE_FREEZE.tar.gz"
rm -f "$ARCHIVE" "${ARCHIVE}.sha256"
tar --sort=name --owner=0 --group=0 --numeric-owner -czf "$ARCHIVE" "$RESULT_DIR"
sha256sum "$ARCHIVE" > "${ARCHIVE}.sha256"
gzip -t "$ARCHIVE" || fail "Frozen evidence gzip integrity failed."
tar -tzf "$ARCHIVE" >/dev/null || fail "Frozen evidence tar integrity failed."

banner "7/8 RESULTS SNAPSHOT"
echo "Validity:"
cat "$RESULT_DIR/VALIDITY.json"
echo
echo "Aggregate summary:"
cat "$RESULT_DIR/AGGREGATE_SUMMARY.csv"

banner "8/8 COMPLETE"
echo "Campaign:           $CAMPAIGN"
echo "Smoke evidence:     $SMOKE_OUT"
echo "Canonical evidence: $RESULT_DIR"
echo "Frozen archive:     $ARCHIVE"
echo "Archive SHA-256:"
cat "${ARCHIVE}.sha256"
echo
echo "PREFLIGHT:           PASS"
echo "PACKAGE INTEGRITY:   PASS"
echo "SMOKE GATE:          PASS"
echo "CANONICAL EXECUTION: PASS"
echo "EVIDENCE VALIDITY:   PASS"
echo "EVIDENCE FREEZE:     PASS"
echo
echo "SAFE TO COPY EVIDENCE OFF H200"

trap - EXIT
exit 0
