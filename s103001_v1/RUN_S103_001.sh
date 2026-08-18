#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"; CAMPAIGN='GBI-103-H200-S103-001'; LOG="$ROOT/S103_001_BOOTSTRAP_LAST.log"; : > "$LOG"; exec > >(tee -a "$LOG") 2>&1
fail(){ echo; echo '============================================================'; echo "$CAMPAIGN — FAIL-CLOSED"; echo '============================================================'; echo "$1"; echo "No canonical PASS is asserted. Inspect: $LOG"; exit 1; }
banner(){ echo; echo '============================================================'; echo "$1"; echo '============================================================'; }
trap 'rc=$?; if [[ $rc -ne 0 ]]; then echo; echo "FAIL-CLOSED: launcher stopped (exit $rc)."; fi' EXIT
banner '0/8 PACKAGE INTEGRITY'; chmod +x verify_package.sh run_h200.sh RUN_S103_001.sh; ./verify_package.sh || fail 'Frozen package checksum verification failed.'
banner '1/8 H200 PREFLIGHT'; command -v nvidia-smi >/dev/null || fail 'nvidia-smi unavailable'; GPU="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1 | tr -d '\r')"; echo "GPU: $GPU"; [[ "$GPU" == *H200* ]] || fail "Required H200; found $GPU"; echo "Python: $(python3 --version 2>&1)"
banner '2/8 PYTORCH/CUDA RUNTIME'; python3 - <<'PY' || fail 'CUDA/H200 validation failed.'
import torch
print('torch_version =',torch.__version__); print('cuda_build =',torch.version.cuda); print('cuda_available =',torch.cuda.is_available()); print('gpu =',torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE')
assert torch.cuda.is_available() and 'H200' in torch.cuda.get_device_name(0)
PY
banner '3/8 SMOKE GATE'; SMOKE="S103_001_SMOKE_$(date -u +%Y%m%dT%H%M%SZ)"; ./run_h200.sh --smoke --out "$SMOKE" || fail 'Smoke execution failed.'; python3 - "$SMOKE" <<'PY' || fail 'Smoke validity failed.'
import json,pathlib,sys
v=json.loads((pathlib.Path(sys.argv[1])/'VALIDITY.json').read_text()); print('Smoke validity:',v['status']); assert v['status']=='PASS'
PY
banner '4/8 CANONICAL 1M × 5 × DEPTHS 1/2/4/8 RUN'; STAMP="$(date -u +%Y%m%dT%H%M%SZ)"; OUT="GBI_103_H200_S103_001_${STAMP}"; ./run_h200.sh --out "$OUT" || fail 'Canonical execution failed.'
banner '5/8 EVIDENCE VERIFICATION'; python3 - "$OUT" <<'PY' || fail 'Evidence verification failed.'
import hashlib,json,pathlib,sys
r=pathlib.Path(sys.argv[1]); v=json.loads((r/'VALIDITY.json').read_text()); assert v['status']=='PASS'; m=json.loads((r/'SHA256SUMS.json').read_text())
for n,rec in m.items():
 p=r/n; assert p.is_file(); assert hashlib.sha256(p.read_bytes()).hexdigest()==rec['sha256']
print(f'EVIDENCE FILE VERIFICATION PASS ({len(m)} files)')
PY
cp PACKAGE_SHA256SUMS.txt "$OUT/HARNESS_PACKAGE_SHA256SUMS.txt"; cp PREREGISTRATION.json "$OUT/HARNESS_PREREGISTRATION.json"; cp IMPLEMENTATION_MAPPING.json "$OUT/HARNESS_IMPLEMENTATION_MAPPING.json"; cp SOURCE_PROVENANCE.json "$OUT/HARNESS_SOURCE_PROVENANCE.json"; cp INTERPRETATION_LIMITS.txt "$OUT/HARNESS_INTERPRETATION_LIMITS.txt"; cp src/s103_battery.py "$OUT/HARNESS_s103_battery.py"; cp RUN_S103_001.sh "$OUT/HARNESS_RUN_S103_001.sh"
python3 - "$OUT" <<'PY'
import hashlib,json,pathlib,sys
r=pathlib.Path(sys.argv[1]); m={}
for p in sorted(r.iterdir()):
 if p.is_file() and p.name!='SHA256SUMS.json': m[p.name]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
(r/'SHA256SUMS.json').write_text(json.dumps(m,indent=2)+'\n'); print(f'Final evidence manifest written: {len(m)} files')
PY
banner '6/8 READ-ONLY EVIDENCE FREEZE'; chmod -R a-w "$OUT"; ARC="${OUT}_EVIDENCE_FREEZE.tar.gz"; tar --sort=name --owner=0 --group=0 --numeric-owner -czf "$ARC" "$OUT"; sha256sum "$ARC" > "${ARC}.sha256"; gzip -t "$ARC"; tar -tzf "$ARC" >/dev/null
banner '7/8 RESULTS SNAPSHOT'; cat "$OUT/VALIDITY.json"; echo; cat "$OUT/AGGREGATE_SUMMARY.csv"
banner '8/8 COMPLETE'; echo "Campaign: $CAMPAIGN"; echo "Smoke evidence: $SMOKE"; echo "Canonical evidence: $OUT"; echo "Frozen archive: $ARC"; echo 'Archive SHA-256:'; cat "${ARC}.sha256"; echo; echo 'PREFLIGHT: PASS'; echo 'PACKAGE INTEGRITY: PASS'; echo 'SMOKE GATE: PASS'; echo 'CANONICAL EXECUTION: PASS'; echo 'EVIDENCE VALIDITY: PASS'; echo 'EVIDENCE FREEZE: PASS'; echo; echo 'SAFE TO COPY EVIDENCE OFF H200'; trap - EXIT
