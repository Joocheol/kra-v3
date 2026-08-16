#!/usr/bin/env python3
import pathlib, unittest
from collections import defaultdict
import numpy as np
from analyze_cross_market import load_race_records, load_feasible, completed_trifecta, marginalize
from check_coherence import load_month

DATA=pathlib.Path('데이터'); TAILS=(.10,.20,.40); DRAWS=5000; RNG=np.random.default_rng(20260817)
CONFIGS=(('Rmin_uniform','residual_min','uniform',0.0),('Rmid_uniform','residual_mid','uniform',0.0),('Rmax_uniform','residual_max','uniform',0.0),('Rmid_position','residual_mid','position_independent',0.10))
TARGETS=('win','quinella','exacta','trio','trifecta')

def winner_key(a,t):
    x,y,z=a[:3]
    return x if t=='win' else frozenset((x,y)) if t=='quinella' else (x,y) if t=='exacta' else frozenset((x,y,z)) if t=='trio' else (x,y,z)

def oe_parts(pool,winner,frac):
    vals=np.fromiter(pool.values(),float); cut=float(np.quantile(vals,frac,method='higher'))
    tail={k:p for k,p in pool.items() if p<=cut+1e-18}
    return float(winner in tail),float(sum(tail.values()))

def boot_ratio(bydate):
    dates=sorted(bydate); O=np.array([bydate[d][0] for d in dates]); E=np.array([bydate[d][1] for d in dates]); G=len(dates)
    W=RNG.multinomial(G,np.full(G,1/G),size=DRAWS)
    rb=(W@O)/(W@E); point=O.sum()/E.sum(); lo,hi=np.quantile(rb,[.025,.975]); return point,float(lo),float(hi),G

class ClusterFivePool(unittest.TestCase):
  def test_clustered(self):
    races=load_race_records(DATA/'races.jsonl.gz'); feas=load_feasible(DATA/'trifecta_feasible_sets.csv.gz')
    months=sorted({r['date'][:7] for rid,r in races.items() if rid in feas and feas[rid]['capped_cells']>0})
    bd=defaultdict(lambda:defaultdict(lambda:[0.,0.]))
    for mi,month in enumerate(months,1):
      mkts=load_month(DATA,month)
      for rid,m in mkts.items():
        race=races.get(rid); info=feas.get(rid)
        if race is None or info is None or info['capped_cells']<=0 or not m.get('trifecta'): continue
        arr=tuple((race.get('arrival') or [])[:3])
        if len(arr)!=3 or len(set(arr))!=3: continue
        for cn,sc,al,beta in CONFIGS:
          tri=completed_trifecta(race,m['trifecta'],info,sc,allocation=al,beta=beta); pools=marginalize(tri); pools['trifecta']=tri
          for target in TARGETS:
            w=winner_key(arr,target)
            if w not in pools[target]: continue
            for f in TAILS:
              o,e=oe_parts(pools[target],w,f)
              for sample in ('pooled','2025' if race['date'][:4]=='2025' else 'other'):
                if sample=='other': continue
                x=bd[(sample,cn,target,f)][race['date']]; x[0]+=o; x[1]+=e
      print(f'# month {mi}/{len(months)} {month}',flush=True)
    print('FIVE_POOL_CLUSTER_INFERENCE')
    for sample in ('pooled','2025'):
      print('SAMPLE',sample); robust=0; total=0
      for t in TARGETS:
        for f in TAILS:
          rs=[]
          for cn,_,_,_ in CONFIGS:
            p,lo,hi,g=boot_ratio(bd[(sample,cn,t,f)]); rs.append((cn,p,lo,hi,g))
          total+=1
          cls='ROBUST_FLB' if max(x[3] for x in rs)<1 else 'ROBUST_REVERSE' if min(x[2] for x in rs)>1 else 'UNCERTAIN'
          if cls!='UNCERTAIN': robust+=1
          det=';'.join(f'{x[0]}={x[1]:.3f}[{x[2]:.3f},{x[3]:.3f}]' for x in rs)
          print(f'{t},tail={f:.2f},{cls},{det},dates={rs[0][4]}')
      print(f'CLASSIFIED={robust}/{total}')
    self.fail('intentional diagnostic stop after output')
