#!/usr/bin/env python3
import argparse, csv, hashlib, json, os, pathlib, random, shutil, statistics, subprocess, sys, threading, time
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]

def load_json(p):
    with open(p) as f: return json.load(f)

def sha256_file(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20), b''): h.update(b)
    return h.hexdigest()

def gpu_preflight(required):
    try:
        q=subprocess.check_output(['nvidia-smi','--query-gpu=name,uuid,driver_version,memory.total','--format=csv,noheader,nounits'], text=True).strip().splitlines()[0]
    except Exception as e:
        raise SystemExit(f'FAIL-CLOSED: live NVIDIA GPU/nvidia-smi required: {e}')
    name=q.split(',')[0].strip()
    if required not in name:
        raise SystemExit(f'FAIL-CLOSED: required GPU containing {required!r}; found {name!r}')
    try:
        import torch
    except Exception as e:
        raise SystemExit(f'FAIL-CLOSED: PyTorch is required for native CUDA work: {e}')
    if not torch.cuda.is_available():
        raise SystemExit('FAIL-CLOSED: torch.cuda.is_available() is false')
    if required not in torch.cuda.get_device_name(0):
        raise SystemExit(f'FAIL-CLOSED: torch device is {torch.cuda.get_device_name(0)!r}')
    return torch, q

def policy_truth(event_id, auth_fraction):
    period=max(1, round(1/auth_fraction))
    return (event_id % period)==0

def run_arm(torch, arm, events, depth, cfg, seed):
    rnd=random.Random(seed)
    auth_frac=cfg['authorization_fraction']; bf=cfg['branch_factor']
    authorized=0; false_auth=0; false_excl=0; instantiated=0; prevented=0; post_discard=0
    trace=[]
    t0=time.perf_counter(); ev0=torch.cuda.Event(enable_timing=True); ev1=torch.cuda.Event(enable_timing=True)
    dim=cfg['tensor_dim']; iters=cfg['gpu_work_iterations']
    x=torch.ones((dim,dim), device='cuda', dtype=torch.float32)
    ev0.record()
    work_units=0
    for i in range(events):
        truth=policy_truth(i,auth_frac)
        if arm=='RANDOM_GATE': decision=(rnd.random()<auth_frac)
        elif arm in ('CPA_PRIOR_ART','CPA_PLUS_GBI','GBI_ONLY','DISPLACED_GBI','ORACLE'): decision=truth
        else: raise RuntimeError(arm)
        authorized += int(decision)
        false_auth += int(decision and not truth)
        false_excl += int((not decision) and truth)
        if arm=='CPA_PRIOR_ART':
            inst=True
            if not decision: post_discard += 1
        elif arm=='DISPLACED_GBI':
            inst=True
            if not decision: post_discard += 1
        else:
            inst=bool(decision)
            if not inst: prevented += 1
        if inst:
            units=bf**max(0, depth-1)
            instantiated += units
            work_units += 1
        if i < 16:
            tr={"event":i,"truth":truth,"decision":decision,"arm":arm,"depth":depth}
            if arm in ('CPA_PLUS_GBI','GBI_ONLY','ORACLE'):
                tr.update({"authorization_before_boundary":True,"boundary_crossed":inst,"isp_acquired":inst,"mrc_started":inst})
            elif arm=='DISPLACED_GBI':
                tr.update({"boundary_crossed":True,"isp_acquired":True,"mrc_started":True,"governance_after_isp":True})
            else:
                tr.update({"source_ambiguous_vm_instantiation":True,"associated_service_authorized":decision})
            trace.append(tr)
    loops=max(1, int((work_units/events)*iters))
    y=x
    for _ in range(loops): y=torch.relu(y @ x / dim)
    ev1.record(); torch.cuda.synchronize()
    gpu_ms=ev0.elapsed_time(ev1); wall=time.perf_counter()-t0
    potential=events*(bf**max(0,depth-1))
    return {
        "arm":arm,"depth":depth,"events":events,"authorized_events":authorized,
        "false_authorizations":false_auth,"false_exclusions":false_excl,
        "instantiated_structural_units":instantiated,"potential_structural_units":potential,
        "prevented_isp_events":prevented,"post_instantiation_discard_events":post_discard,
        "gpu_proxy_elapsed_s":gpu_ms/1000.0,"wall_duration_s":wall,"trace_sample":trace
    }

def telemetry_thread(stop, path, interval):
    fields='timestamp,power.draw,utilization.gpu,memory.used,temperature.gpu'
    with open(path,'w') as out:
        out.write('timestamp,power_w,gpu_util_pct,memory_used_mib,temp_c\n')
        while not stop.is_set():
            try:
                line=subprocess.check_output(['nvidia-smi',f'--query-gpu={fields}','--format=csv,noheader,nounits'],text=True).strip().splitlines()[0]
                out.write(line+'\n'); out.flush()
            except Exception as e:
                out.write(f'ERROR,{e}\n'); out.flush()
            stop.wait(interval)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--smoke',action='store_true'); ap.add_argument('--out'); args=ap.parse_args()
    cfg=load_json(ROOT/'config/CONFIG_FROZEN.json'); torch,gpuq=gpu_preflight(cfg['required_gpu_name_substring'])
    if args.smoke:
        events=cfg['smoke_events']; reps=cfg['smoke_repeats']; depths=cfg['smoke_depths']
    else:
        events=cfg['events']; reps=cfg['repeats']; depths=cfg['depths']
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=pathlib.Path(args.out or f'GBI_103_H200_CPA_001_{stamp}'); out.mkdir(parents=True, exist_ok=False)
    env={"utc_start":stamp,"hostname":os.uname().nodename,"platform":' '.join(os.uname()),"gpu_query":gpuq,
         "gpu_name":torch.cuda.get_device_name(0),"torch":torch.__version__,"cuda_runtime":torch.version.cuda,
         "device_compute_capability":torch.cuda.get_device_capability(0)}
    (out/'ENVIRONMENT.json').write_text(json.dumps(env,indent=2))
    shutil.copy(ROOT/'config/CONFIG_FROZEN.json',out/'CONFIG_FROZEN.json')
    shutil.copy(ROOT/'PREREGISTRATION.json',out/'PREREGISTRATION.json')
    shutil.copy(ROOT/'SOURCE_PROVENANCE.json',out/'SOURCE_PROVENANCE.json')
    shutil.copy(ROOT/'IMPLEMENTATION_MAPPING.json',out/'IMPLEMENTATION_MAPPING.json')
    (out/'IMPLEMENTATION_ASSUMPTIONS.json').write_text(json.dumps({"assumptions":["CPA_PRIOR_ART preserves source ambiguity by not treating policy denial as retroactively preventing an already-instantiated VM structural unit; associated policy-controlled service provisioning remains decision-gated."]},indent=2))
    stop=threading.Event(); tt=threading.Thread(target=telemetry_thread,args=(stop,out/'NVIDIA_SMI_TELEMETRY.csv',cfg['telemetry_interval_ms']/1000),daemon=True); tt.start()
    time.sleep(cfg['idle_baseline_seconds'])
    rows=[]; traces=[]; order=[]; n=0
    try:
      for rep in range(1,reps+1):
        for depth in depths:
          arms=list(cfg['arms']); rr=random.Random(cfg['seed']+rep*1000+depth); rr.shuffle(arms)
          for arm in arms:
            n+=1; print(f'RUN order={n} rep={rep}/{reps} depth={depth} arm={arm}',flush=True)
            r=run_arm(torch,arm,events,depth,cfg,cfg['seed']+rep*100000+depth*100+cfg['arms'].index(arm))
            r.update({"repeat":rep,"order":n}); traces.extend(r.pop('trace_sample')); rows.append(r); order.append({"order":n,"repeat":rep,"depth":depth,"arm":arm})
            time.sleep(cfg['inter_arm_cooldown_ms']/1000)
    finally:
      stop.set(); tt.join(timeout=2)
    with open(out/'RESULTS.jsonl','w') as f:
        for r in rows: f.write(json.dumps(r,sort_keys=True)+'\n')
    with open(out/'EVENT_TRACES.jsonl','w') as f:
        for r in traces: f.write(json.dumps(r,sort_keys=True)+'\n')
    (out/'ARM_ORDER.json').write_text(json.dumps(order,indent=2))
    fields=[k for k in rows[0].keys()]
    with open(out/'SUMMARY.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    agg=[]
    for depth in depths:
      g=[r for r in rows if r['depth']==depth and r['arm']=='GBI_ONLY']
      gi=statistics.median([r['instantiated_structural_units'] for r in g]); gg=statistics.median([r['gpu_proxy_elapsed_s'] for r in g]); gw=statistics.median([r['wall_duration_s'] for r in g])
      for arm in cfg['arms']:
        a=[r for r in rows if r['depth']==depth and r['arm']==arm]
        agg.append({"depth":depth,"arm":arm,"median_instantiation_ratio_vs_gbi":statistics.median([r['instantiated_structural_units'] for r in a])/gi if gi else None,
                    "median_gpu_proxy_elapsed_ratio_vs_gbi":statistics.median([r['gpu_proxy_elapsed_s'] for r in a])/gg if gg else None,
                    "median_wall_duration_ratio_vs_gbi":statistics.median([r['wall_duration_s'] for r in a])/gw if gw else None,
                    "max_false_authorizations":max(r['false_authorizations'] for r in a),"max_false_exclusions":max(r['false_exclusions'] for r in a)})
    with open(out/'AGGREGATE_SUMMARY.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=agg[0].keys()); w.writeheader(); w.writerows(agg)
    valid=True; reasons=[]
    for r in rows:
      if r['arm'] in ('CPA_PLUS_GBI','GBI_ONLY','ORACLE') and (r['false_authorizations'] or r['false_exclusions']): valid=False; reasons.append(f"fidelity:{r['arm']} rep={r['repeat']} depth={r['depth']}")
      if r['arm']=='CPA_PRIOR_ART' and r['prevented_isp_events']!=0: valid=False; reasons.append('CPA_PRIOR_ART illegally used GBI-style ISP prevention')
    val={"status":"PASS" if valid else "FAIL","primary_measure":"instantiated_structural_units","hardware_measure":"bounded CUDA stress proxy only","reasons":reasons,
         "cpa_mapping_rule":"CPA_PRIOR_ART may not retroactively prevent/count-away an already instantiated VM structural unit; associated service authorization remains separately modeled."}
    (out/'VALIDITY.json').write_text(json.dumps(val,indent=2))
    if not valid: raise SystemExit('FAIL-CLOSED: validity checks failed; see VALIDITY.json')
    manifest={}
    for p in sorted(out.iterdir()):
      if p.is_file() and p.name!='SHA256SUMS.json': manifest[p.name]={"sha256":sha256_file(p),"bytes":p.stat().st_size}
    (out/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2))
    print(f'PASS: live evidence written to {out}')

if __name__=='__main__': main()
