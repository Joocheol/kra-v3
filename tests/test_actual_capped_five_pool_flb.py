#!/usr/bin/env python3
import pathlib, unittest
from collections import defaultdict
import numpy as np

from analyze_cross_market import load_race_records, load_feasible, completed_trifecta, marginalize
from check_coherence import load_month

DATA=pathlib.Path('데이터')
TAILS=(.10,.20,.40)
CONFIGS=(
    ('Rmin_uniform','residual_min','uniform',0.0),
    ('Rmid_uniform','residual_mid','uniform',0.0),
    ('Rmax_uniform','residual_max','uniform',0.0),
    ('Rmid_position','residual_mid','position_independent',0.10),
)
TARGETS=('win','quinella','exacta','trio','trifecta')


def winner_key(arrival,target):
    a,b,c=arrival[:3]
    if target=='win': return a
    if target=='quinella': return frozenset((a,b))
    if target=='exacta': return (a,b)
    if target=='trio': return frozenset((a,b,c))
    if target=='trifecta': return (a,b,c)
    raise KeyError(target)


def tail_stats(pool,winner,frac):
    vals=np.asarray(list(pool.values()),dtype=float)
    cutoff=float(np.quantile(vals,frac,method='higher'))
    tail={k:p for k,p in pool.items() if p<=cutoff+1e-18}
    return (1 if winner in tail else 0), float(sum(tail.values())), len(tail), len(pool)


class ActualCappedFivePoolFLB(unittest.TestCase):
    def test_actual_capped_five_pool(self):
        races=load_race_records(DATA/'races.jsonl.gz')
        feasible=load_feasible(DATA/'trifecta_feasible_sets.csv.gz')
        months=sorted({r['date'][:7] for rid,r in races.items() if rid in feasible and feasible[rid]['capped_cells']>0})
        acc=defaultdict(lambda:[0.0,0.0,0,0,0]) # O,E,races,tailcells,totalcells
        used=defaultdict(set)
        errors=0
        for mi,month in enumerate(months,1):
            markets=load_month(DATA,month)
            for rid,market in markets.items():
                race=races.get(rid); info=feasible.get(rid)
                if race is None or info is None or info['capped_cells']<=0 or not market.get('trifecta'): continue
                arr=tuple((race.get('arrival') or [])[:3])
                if len(arr)!=3 or len(set(arr))!=3: continue
                for cname,scenario,allocation,beta in CONFIGS:
                    try:
                        tri=completed_trifecta(race,market['trifecta'],info,scenario,allocation=allocation,beta=beta)
                    except Exception:
                        errors+=1; continue
                    pools=marginalize(tri); pools['trifecta']=tri
                    for target in TARGETS:
                        winner=winner_key(arr,target)
                        pool=pools[target]
                        if winner not in pool: continue
                        for frac in TAILS:
                            o,e,nt,n=tail_stats(pool,winner,frac)
                            for sample in ('pooled',race['date'][:4]):
                                key=(sample,cname,target,frac)
                                a=acc[key]; a[0]+=o; a[1]+=e; a[2]+=1; a[3]+=nt; a[4]+=n
                                used[(sample,cname)].add(rid)
            print(f'# month {mi}/{len(months)} {month}',flush=True)
        print('ACTUAL_CAPPED_FIVE_POOL_FLB')
        print(f'completion_errors={errors}')
        for sample in ('pooled','2022','2023','2024','2025'):
            print(f'SAMPLE {sample}')
            for target in TARGETS:
                for frac in TAILS:
                    rows=[]
                    for cname,_,_,_ in CONFIGS:
                        O,E,n,nt,nall=acc[(sample,cname,target,frac)]
                        if n==0: continue
                        rows.append((cname,O/E,O,E,n,nt/n,nall/n))
                    if not rows: continue
                    ratios=[x[1] for x in rows]
                    direction='ALL_LT1' if max(ratios)<1 else 'ALL_GT1' if min(ratios)>1 else 'CROSSES1'
                    detail=';'.join(f'{x[0]}={x[1]:.4f}' for x in rows)
                    print(f'{target},tail={frac:.2f},{direction},range=[{min(ratios):.4f},{max(ratios):.4f}],{detail},races={rows[0][4]}')
        # compact pooled sensitivity summary
        stable=total=0
        for target in TARGETS:
            for frac in TAILS:
                ratios=[]
                for cname,_,_,_ in CONFIGS:
                    O,E,n,_,_=acc[('pooled',cname,target,frac)]
                    if n: ratios.append(O/E)
                if ratios:
                    total+=1
                    if max(ratios)<1 or min(ratios)>1: stable+=1
        print(f'POOLED_DIRECTION_STABLE={stable}/{total}')
        self.assertGreater(len(used[('pooled','Rmid_uniform')]),5000)
        self.fail('intentional diagnostic stop after output')
