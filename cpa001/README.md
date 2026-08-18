# GBI-103-H200-CPA-001 — H200 Plug-and-Play

Preregistered closest-prior-art VM-policy architectural comparator and dependency-ablation battery.

## One-command execution

From inside this directory on the NVIDIA H200:

```bash
./RUN_CPA_001.sh
```

The launcher automatically:

1. verifies the frozen package;
2. requires an NVIDIA H200 and `nvidia-smi`;
3. verifies PyTorch/CUDA and repairs the CUDA-13 PyTorch runtime if absent;
4. executes the smoke gate;
5. executes the canonical 1,000,000-event × 5-repeat × depths 1/2/4/8 six-arm campaign;
6. verifies evidence hashes and validity;
7. embeds the exact harness/preregistration/provenance records into the evidence;
8. makes the evidence directory read-only;
9. creates and integrity-tests a frozen evidence archive and SHA-256;
10. prints the aggregate result and the final evidence archive/hash.

No valid adverse result is discarded. A failure does not produce a canonical PASS.

Canonical campaign ID: `GBI-103-H200-CPA-001`.
