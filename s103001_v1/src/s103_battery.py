#!/usr/bin/env python3
import argparse,csv,hashlib,json,os,pathlib,random,shutil,statistics,subprocess,threading,time
from datetime import datetime,timezone
ROOT=pathlib.Path(__file__).resolve().parents[1]
def J(p): return json.loads(pathlib.Path(p).read_text())
def H(p):
 h=hashlib.sha256();
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def preflight(req):
 q=subprocess.check_output(['nvidia-smi','--query-gpu=name,uuid,driver_version,memory.total','--format=csv,noheader,nounits'],text=True).strip().splitlines()[0]
 name=q.split(',')[0].strip()
 if req not in name: raise SystemExit(f'FAIL-CLOSED: required {req}; found {name}')
 import torch
 if not torch.cuda.is_available() or req not in torch.cuda.get_device_name(0): raise SystemExit('FAIL-CLOSED: CUDA/H200 unavailable')
 return torch,q
def truth(i,a): return (i % max(1,round(1/a)))==0
def run_arm(torch,arm,events,depth,cfg,seed):
 rnd=random.Random(seed); a=cfg['authorization_fraction']; bf=cfg['branch_factor']
 auth=fa=fe=inst=prevent_isp=discard=prevent_mrc=0; trace=[]
 x=torch.ones((cfg['tensor_dim'],cfg['tensor_dim']),device='cuda'); e0=torch.cuda.Event(True); e1=torch.cuda.Event(True); t0=time.perf_counter(); e0.record(); work=0
 for i in range(events):
  t=truth(i,a); d=(rnd.random()<a) if arm=='RANDOM_GATE' else t
  auth+=int(d); fa+=int(d and not t); fe+=int((not d) and t)
  if arm in ('S103_COMBINATION_PLUS_GBI','GBI_ONLY','ORACLE','RANDOM_GATE'):
   isp=bool(d); mrc=bool(d); prevent_isp+=int(not d); prevent_mrc+=int(not d)
  elif arm in ('AUTH_RESERVE_ONLY','S103_STRONG_COMBINATION'):
   isp=True; mrc=bool(d); prevent_mrc+=int(not d)
  elif arm=='DISPLACED_GBI':
   isp=True; mrc=True; discard+=int(not d)
  else: raise RuntimeError(arm)
  units=bf**max(0,depth-1) if isp else 0; inst+=units; work+=int(mrc)
  if i<16: trace.append({'event':i,'truth':t,'decision':d,'arm':arm,'depth':depth,'isp_acquired':isp,'mrc_started':mrc})
 loops=max(1,int((work/events)*cfg['gpu_work_iterations'])); y=x
 for _ in range(loops): y=torch.relu(y@x/cfg['tensor_dim'])
 e1.record(); torch.cuda.synchronize(); wall=time.perf_counter()-t0
 return {'arm':arm,'depth':depth,'events':events,'authorized_events':auth,'false_authorizations':fa,'false_exclusions':fe,'instantiated_structural_units':inst,'prevented_isp_events':prevent_isp,'prevented_mrc_events':prevent_mrc,'post_instantiation_discard_events':discard,'gpu_proxy_elapsed_s':e0.elapsed_time(e1)/1000.0,'wall_duration_s':wall,'trace_sample':trace}
def telemetry(stop,path,interval):
 fields='timestamp,power.draw,utilization.gpu,memory.used,temperature.gpu'
 with open(path,'w') as out:
  out.write('timestamp,power_w,gpu_util_pct,memory_used_mib,temp_c\n')
  while not stop.is_set():
   try: out.write(subprocess.check_output(['nvidia-smi',f'--query-gpu={fields}','--format=csv,noheader,nounits'],text=True).strip().splitlines()[0]+'\n'); out.flush()
   except Exception as e: out.write(f'ERROR,{e}\n'); out.flush()
   stop.wait(interval)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--smoke',action='store_true'); ap.add_argument('--out'); args=ap.parse_args(); cfg=J(ROOT/'config/CONFIG_FROZEN.json'); torch,gpuq=preflight(cfg['required_gpu_name_substring'])
 events=cfg['smoke_events'] if args.smoke else cfg['events']; reps=cfg['smoke_repeats'] if args.smoke else cfg['repeats']; depths=cfg['smoke_depths'] if args.smoke else cfg['depths']
 out=pathlib.Path(args.out or f"GBI_103_H200_S103_001_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"); out.mkdir(parents=True,exist_ok=False)
 (out/'ENVIRONMENT.json').write_text(json.dumps({'utc_start':datetime.now(timezone.utc).isoformat(),'hostname':os.uname().nodename,'gpu_query':gpuq,'gpu_name':torch.cuda.get_device_name(0),'torch':torch.__version__,'cuda_runtime':torch.version.cuda},indent=2))
 for n in ['PREREGISTRATION.json','SOURCE_PROVENANCE.json','IMPLEMENTATION_MAPPING.json','INTERPRETATION_LIMITS.txt']: shutil.copy(ROOT/n,out/n)
 shutil.copy(ROOT/'config/CONFIG_FROZEN.json',out/'CONFIG_FROZEN.json')
 stop=threading.Event(); th=threading.Thread(target=telemetry,args=(stop,out/'NVIDIA_SMI_TELEMETRY.csv',cfg['telemetry_interval_ms']/1000),daemon=True); th.start(); time.sleep(cfg['idle_baseline_seconds'])
 rows=[]; traces=[]; order=[]; n=0
 try:
  for rep in range(1,reps+1):
   for depth in depths:
    arms=list(cfg['arms']); random.Random(cfg['seed']+rep*1000+depth).shuffle(arms)
    for arm in arms:
     n+=1; print(f'RUN order={n} rep={rep}/{reps} depth={depth} arm={arm}',flush=True)
     r=run_arm(torch,arm,events,depth,cfg,cfg['seed']+rep*100000+depth*100+cfg['arms'].index(arm)); r.update({'repeat':rep,'order':n}); traces.extend(r.pop('trace_sample')); rows.append(r); order.append({'order':n,'repeat':rep,'depth':depth,'arm':arm}); time.sleep(cfg['inter_arm_cooldown_ms']/1000)
 finally: stop.set(); th.join(timeout=2)
 with open(out/'RESULTS.jsonl','w') as f:
  for r in rows: f.write(json.dumps(r,sort_keys=True)+'\n')
 with open(out/'EVENT_TRACES.jsonl','w') as f:
  for r in traces: f.write(json.dumps(r,sort_keys=True)+'\n')
 (out/'ARM_ORDER.json').write_text(json.dumps(order,indent=2)); fields=list(rows[0].keys())
 with open(out/'SUMMARY.csv','w',newline='') as f: w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
 agg=[]
 for depth in depths:
  g=[r for r in rows if r['depth']==depth and r['arm']=='GBI_ONLY']; gi=statistics.median([r['instantiated_structural_units'] for r in g]); gg=statistics.median([r['gpu_proxy_elapsed_s'] for r in g]); gw=statistics.median([r['wall_duration_s'] for r in g])
  for arm in cfg['arms']:
   arows=[r for r in rows if r['depth']==depth and r['arm']==arm]
   agg.append({'depth':depth,'arm':arm,'median_instantiation_ratio_vs_gbi':statistics.median([r['instantiated_structural_units'] for r in arows])/gi,'median_gpu_proxy_elapsed_ratio_vs_gbi':statistics.median([r['gpu_proxy_elapsed_s'] for r in arows])/gg,'median_wall_duration_ratio_vs_gbi':statistics.median([r['wall_duration_s'] for r in arows])/gw,'max_false_authorizations':max(r['false_authorizations'] for r in arows),'max_false_exclusions':max(r['false_exclusions'] for r in arows)})
 with open(out/'AGGREGATE_SUMMARY.csv','w',newline='') as f: w=csv.DictWriter(f,fieldnames=agg[0].keys()); w.writeheader(); w.writerows(agg)
 ok=True; reasons=[]
 for r in rows:
  if r['arm'] in ('S103_COMBINATION_PLUS_GBI','GBI_ONLY','ORACLE') and (r['false_authorizations'] or r['false_exclusions']): ok=False; reasons.append('fidelity')
  if r['arm'] in ('AUTH_RESERVE_ONLY','S103_STRONG_COMBINATION') and r['prevented_isp_events']!=0: ok=False; reasons.append('prior-art arm illegally prevented ISP')
  if r['arm']=='DISPLACED_GBI' and r['prevented_isp_events']!=0: ok=False; reasons.append('displaced arm illegally prevented ISP')
 val={'status':'PASS' if ok else 'FAIL','primary_measure':'instantiated_structural_units','hardware_measure':'bounded CUDA stress proxy only','reasons':reasons,'strong_combination_rule':'Pre-resource authorization is credited; only pre-ISP prevention counts as satisfying the GBI dependency placement in this battery.'}
 (out/'VALIDITY.json').write_text(json.dumps(val,indent=2));
 if not ok: raise SystemExit('FAIL-CLOSED: validity failed')
 manifest={}
 for p in sorted(out.iterdir()):
  if p.is_file() and p.name!='SHA256SUMS.json': manifest[p.name]={'sha256':H(p),'bytes':p.stat().st_size}
 (out/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2)); print(f'PASS: live evidence written to {out}')
if __name__=='__main__': main()
