#!/usr/bin/env python3
import math, pathlib, unittest
from collections import defaultdict
from decimal import Decimal
import numpy as np

from analyze_masked_reconstruction import _won, bounded_integer_projection, load_races, reconstruct_counts
from analyze_rank_profile_imputation import (
    load_feasible, uncapped_ids, load_grids, predict_hidden, uniform_hidden,
    internal_assignment_scores,
)
from kra.feasible import capped_ticket_upper
from kra.rank_profile import rank_profile, fit_rank_profile_mixture, hidden_total_interval, assign_ranked_counts

DATA=pathlib.Path('데이터')
THRESHOLDS=(7000.0,9000.0)
TAILS=(0.10,0.20,0.40)
DRAWS=5000
SEED=20260817


def marginalize(counts, combos):
    out={k:defaultdict(float) for k in ('win','quinella','exacta','trio','trifecta')}
    total=float(np.sum(counts))
    for combo,n in zip(combos,counts):
        p=float(n)/total; a,b,c=combo
        out['trifecta'][combo]+=p
        out['win'][a]+=p
        out['exacta'][(a,b)]+=p
        out['quinella'][frozenset((a,b))]+=p
        out['trio'][frozenset((a,b,c))]+=p
    return {k:dict(v) for k,v in out.items()}


def winner_key(arrival,target):
    a,b,c=arrival[:3]
    return {'win':a,'exacta':(a,b),'quinella':frozenset((a,b)),'trio':frozenset((a,b,c)),'trifecta':(a,b,c)}[target]


def tail_record(prob,winner,frac):
    items=sorted(prob.items(), key=lambda kv:(kv[1],str(kv[0])))
    k=max(1,int(round(frac*len(items))))
    chosen=items[:k]
    keys={x for x,_ in chosen}
    return float(winner in keys), float(sum(p for _,p in chosen))


def classify(lo,hi):
    if hi<1.0:return 'FLB'
    if lo>1.0:return 'ANTI'
    return 'UNCERTAIN'


def cluster_oe(records, rng):
    # records: date -> list[(O,E)]
    dates=sorted(records); g=len(dates)
    co=np.asarray([sum(x[0] for x in records[d]) for d in dates],float)
    ce=np.asarray([sum(x[1] for x in records[d]) for d in dates],float)
    point=float(co.sum()/ce.sum())
    w=rng.multinomial(g,np.full(g,1/g),size=DRAWS)
    ratios=(w@co)/(w@ce)
    lo,hi=np.quantile(ratios,[.025,.975])
    return point,float(lo),float(hi)


class VirtualCapFLBClusterCalibration(unittest.TestCase):
    def test_calibration(self):
        races=load_races(DATA/'races.jsonl.gz')
        feasible=load_feasible(DATA/'trifecta_feasible_sets.csv.gz')

        train_ids=uncapped_ids(feasible,years={'2022','2023','2024'})
        train_grids=load_grids(DATA,races,train_ids)
        profiles=[]
        for rid in sorted(train_ids):
            sales=_won(races[rid]['sales']['삼쌍승식'])
            x,_,_=reconstruct_counts(sales,train_grids[rid])
            profiles.append(rank_profile(x))
        mixture=fit_rank_profile_mixture(np.stack(profiles))
        del train_grids

        test_ids=uncapped_ids(feasible,years={'2025'})
        grids=load_grids(DATA,races,test_ids)
        # key=(threshold,target,tail,method) -> date -> [(O,E)]
        rec=defaultdict(lambda:defaultdict(list))
        used=defaultdict(int)

        for rid in sorted(grids):
            race=races[rid]; arrival=tuple((race.get('arrival') or [])[:3])
            if len(arrival)!=3 or len(set(arrival))!=3: continue
            values=grids[rid]; combos=[c for c,_ in values]
            sales=_won(race['sales']['삼쌍승식']); total=sales//100
            truth,lower,upper=reconstruct_counts(sales,values)
            truth_probs=marginalize(truth,combos)
            odds=np.asarray([float(v) for _,v in values])
            horses=sorted(set(race['horses'])-set(race.get('scratched') or []))
            date=race['date']
            for threshold in THRESHOLDS:
                hidden=odds>=threshold
                if not hidden.any() or hidden.all() or np.any(lower[hidden]!=upper[hidden]): continue
                visible=~hidden; cap=capped_ticket_upper(sales,cap=Decimal(str(threshold)))
                try:
                    rlo,rhi=hidden_total_interval(total,lower[visible],upper[visible],np.full(int(hidden.sum()),cap,dtype=np.int64))
                except ValueError:
                    continue
                scenarios={'Rmin_uniform':rlo,'Rmid_uniform':(rlo+rhi)//2,'Rmax_uniform':rhi,'Rmid_rank':(rlo+rhi)//2}
                predictions={}
                for method,resid in scenarios.items():
                    target=np.asarray([.73*total/float(v) for _,v in values])
                    base=np.zeros(len(values),dtype=np.int64)
                    base[visible]=bounded_integer_projection(target[visible],lower[visible],upper[visible],total-resid)
                    if method=='Rmid_rank':
                        pred,_,_,_=predict_hidden(mixture,base,visible,hidden,combos,horses,total_tickets=total,hidden_tickets=resid,upper=cap)
                    else:
                        ranked=uniform_hidden(resid,int(hidden.sum()),cap)
                        scores=internal_assignment_scores(combos,base,visible,hidden,horses)
                        pred=assign_ranked_counts(ranked,scores)
                    full=base.copy(); full[hidden]=pred
                    predictions[method]=marginalize(full,combos)
                used[threshold]+=1
                for target_name in ('win','quinella','exacta','trio','trifecta'):
                    wk=winner_key(arrival,target_name)
                    for frac in TAILS:
                        o,e=tail_record(truth_probs[target_name],wk,frac)
                        rec[(threshold,target_name,frac,'truth')][date].append((o,e))
                        for method,pp in predictions.items():
                            o2,e2=tail_record(pp[target_name],wk,frac)
                            rec[(threshold,target_name,frac,method)][date].append((o2,e2))

        rng=np.random.default_rng(SEED)
        methods=('Rmin_uniform','Rmid_uniform','Rmax_uniform','Rmid_rank')
        summary={m:{'total':0,'class_match':0,'spurious':0,'missed':0,'opposite':0,'point_dir_match':0} for m in methods}
        print('VIRTUAL_CAP_FLB_CLUSTER_CALIBRATION')
        print('usable '+','.join(f'{int(t)}:{used[t]}' for t in THRESHOLDS))
        for threshold in THRESHOLDS:
            print(f'THRESHOLD {threshold:.0f}')
            for target_name in ('win','quinella','exacta','trio','trifecta'):
                for frac in TAILS:
                    tp,tlo,thi=cluster_oe(rec[(threshold,target_name,frac,'truth')],rng)
                    tc=classify(tlo,thi)
                    parts=[]
                    for method in methods:
                        mp,mlo,mhi=cluster_oe(rec[(threshold,target_name,frac,method)],rng)
                        mc=classify(mlo,mhi); s=summary[method]; s['total']+=1
                        s['class_match']+=int(mc==tc)
                        s['spurious']+=int(tc=='UNCERTAIN' and mc!='UNCERTAIN')
                        s['missed']+=int(tc!='UNCERTAIN' and mc=='UNCERTAIN')
                        s['opposite']+=int(tc!='UNCERTAIN' and mc!='UNCERTAIN' and mc!=tc)
                        s['point_dir_match']+=int((tp<1)==(mp<1))
                        parts.append(f'{method}={mp:.3f}[{mlo:.3f},{mhi:.3f}]/{mc}')
                    print(f'{target_name},tail={frac:.2f},truth={tp:.3f}[{tlo:.3f},{thi:.3f}]/{tc};'+';'.join(parts))
        for method,s in summary.items():
            print('SUMMARY',method,','.join(f'{k}={v}' for k,v in s.items()))
        self.assertGreaterEqual(used[7000.0],250)
        self.assertGreaterEqual(used[9000.0],80)
        self.fail('intentional diagnostic stop after output')
