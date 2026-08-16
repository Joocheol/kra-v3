#!/usr/bin/env python3
"""Test whether trifecta tail reconstruction preserves FLB after marginalization.

This is a diagnostic, not a maintained output.  On 2025 races with no real
trifecta 9999.9 cell, create virtual caps at 7000 and 9000, reconstruct the
hidden trifecta tail with three existing methods under identical accounting
bounds, marginalize each completed trifecta distribution to win/exacta/
quinella/trio, and compare FLB summaries with the fully observed truth.

FLB summaries are deliberately pool-agnostic:
1. O/E for the least-bet 10%, 20%, and 40% of states within each race;
2. an ordinal calibration moment, winner fractional rank minus the market-
   mass-weighted mean fractional rank (negative = longshot-overbetting direction).
"""
from __future__ import annotations

import math
import pathlib
from collections import defaultdict
from decimal import Decimal

import numpy as np

from analyze_cross_market import marginalize
from analyze_masked_reconstruction import _won, bounded_integer_projection, load_grids, reconstruct_counts
from analyze_power_law_rank_audit import fit_training, power_cell_scores
from analyze_rank_profile_correction import (
    bounded_weight_allocation_bounds,
    hidden_total_interval_bounds,
    predict_hidden_bounds,
)
from analyze_rank_profile_imputation import uncapped_ids
from kra.feasible import capped_ticket_upper

DATA=pathlib.Path('데이터')
THRESHOLDS=(Decimal('7000.0'),Decimal('9000.0'))
TAIL_FRACS=(0.10,0.20,0.40)
TARGETS=('win','quinella','exacta','trio','trifecta')
MODELS=('uniform','rank_profile','shifted_power')


def normalized(d):
    s=float(sum(d.values()))
    return {k:float(v)/s for k,v in d.items()}


def all_pools(trifecta):
    tri=normalized(trifecta)
    out=marginalize(tri)
    out['trifecta']=tri
    return out


def realised_keys(race):
    arr=tuple((race.get('arrival') or [])[:3])
    if len(arr)!=3 or len(set(arr))!=3:
        return None
    a,b,c=arr
    return {
        'win':a,
        'exacta':(a,b),
        'quinella':frozenset((a,b)),
        'trio':frozenset((a,b,c)),
        'trifecta':(a,b,c),
    }


def rank_stats(prob, winner, frac):
    keys=sorted(prob, key=lambda k:(-prob[k],str(k)))
    if winner not in prob or len(keys)<2:return None
    n=len(keys)
    ranks={k:i/(n-1) for i,k in enumerate(keys)}  # 0 favorite, 1 longest
    expected=sum(prob[k]*ranks[k] for k in keys)
    ordinal=ranks[winner]-expected
    m=max(1,int(math.ceil(frac*n)))
    tail=set(keys[-m:])
    E=sum(prob[k] for k in tail)
    O=int(winner in tail)
    return E,O,ordinal


def reconstruct_models(race,values,mixture,threshold):
    sales=_won(race['sales']['삼쌍승식']); total=sales//100
    truth,lower,upper=reconstruct_counts(sales,values)
    odds=np.asarray([float(v) for _,v in values],dtype=float)
    hidden=odds>=float(threshold); visible=~hidden
    if not hidden.any() or hidden.all() or np.any(lower[hidden]!=upper[hidden]):return None
    combos=[c for c,_ in values]
    horses=sorted(set(race['horses'])-set(race.get('scratched') or []))
    U=capped_ticket_upper(sales,cap=threshold)
    hlo=np.ones(int(hidden.sum()),dtype=np.int64)
    hhi=np.full(int(hidden.sum()),U,dtype=np.int64)
    try:
        rlo,rhi=hidden_total_interval_bounds(total,lower[visible],upper[visible],hlo,hhi)
    except ValueError:
        return None
    R=(rlo+rhi)//2
    target=np.asarray([0.73*total/float(v) for _,v in values])
    base=np.zeros(len(values),dtype=np.int64)
    base[visible]=bounded_integer_projection(target[visible],lower[visible],upper[visible],total-R)

    truth_share={c:float(n)/total for c,n in zip(combos,truth)}
    outputs={'truth':truth_share}
    uni=bounded_weight_allocation_bounds(R,np.ones(int(hidden.sum())),hlo,hhi)
    rp,_,_=predict_hidden_bounds(
        mixture,base,visible,hidden,combos,horses,total_tickets=total,
        hidden_tickets=R,lower=hlo,upper=hhi,
    )
    ps,_=power_cell_scores(base,visible,hidden,combos,horses,shifted=True)
    sp=bounded_weight_allocation_bounds(R,ps,hlo,hhi)
    for name,pred in [('uniform',uni),('rank_profile',rp),('shifted_power',sp)]:
        x=base.copy(); x[hidden]=pred
        outputs[name]={c:float(n)/total for c,n in zip(combos,x)}
    return outputs,int(hidden.sum()),rlo,rhi,int(truth[hidden].sum())


def main():
    races,feasible,mixture,bounds,_=fit_training(DATA)
    ids=uncapped_ids(feasible,years={'2025'})
    grids=load_grids(DATA,races,ids)
    print('FLB_PRESERVATION_VIRTUAL_CAP')
    print(f'clean_2025_races={len(ids)}')
    for threshold in THRESHOLDS:
        sums=defaultdict(lambda:{'E':0.0,'O':0,'ord':0.0,'n':0})
        diagnostics=[]
        used=0
        for rid in sorted(ids):
            keys=realised_keys(races[rid])
            if keys is None:continue
            rec=reconstruct_models(races[rid],grids[rid],mixture,threshold)
            if rec is None:continue
            outputs,hcells,rlo,rhi,trueR=rec; used+=1
            diagnostics.append((hcells,rhi-rlo,abs(((rlo+rhi)//2)-trueR)))
            for model,tri in outputs.items():
                pools=all_pools(tri)
                for target in TARGETS:
                    p=pools[target]
                    for frac in TAIL_FRACS:
                        z=rank_stats(p,keys[target],frac)
                        if z is None:continue
                        E,O,ordinal=z
                        d=sums[(model,target,frac)]
                        d['E']+=E;d['O']+=O;d['ord']+=ordinal;d['n']+=1
        print(f'\nTHRESHOLD {threshold} races={used}')
        if diagnostics:
            A=np.asarray(diagnostics,float)
            print(f'DIAGNOSTIC hidden_cells_median={np.median(A[:,0]):.1f} residual_width_median={np.median(A[:,1]):.1f} residual_mid_abs_error_median={np.median(A[:,2]):.1f}')
        print('target,tail_frac,truth_OE,uniform_OE,rank_profile_OE,shifted_power_OE,rank_abs_err,shifted_abs_err,truth_ordinal,uniform_ordinal,rank_ordinal,shifted_ordinal,rank_ordinal_abs_err,shifted_ordinal_abs_err')
        for target in TARGETS:
            for frac in TAIL_FRACS:
                def g(model):
                    d=sums[(model,target,frac)]
                    return d['O']/d['E'] if d['E']>0 else math.nan,d['ord']/d['n']
                t,to=g('truth');u,uo=g('uniform');r,ro=g('rank_profile');s,so=g('shifted_power')
                print(f'{target},{frac:.2f},{t:.6f},{u:.6f},{r:.6f},{s:.6f},{abs(r-t):.6f},{abs(s-t):.6f},{to:.6f},{uo:.6f},{ro:.6f},{so:.6f},{abs(ro-to):.6f},{abs(so-to):.6f}')
        # compact winner count: which method is closest to truth on O/E + ordinal per target/fraction
        score={m:0.0 for m in MODELS}
        direction={m:0 for m in MODELS}
        cells=0
        for target in TARGETS:
            for frac in TAIL_FRACS:
                t,to=(lambda d:(d['O']/d['E'],d['ord']/d['n']))(sums[('truth',target,frac)])
                for m in MODELS:
                    d=sums[(m,target,frac)]; oe=d['O']/d['E']; oo=d['ord']/d['n']
                    score[m]+=abs(oe-t)+abs(oo-to)
                    direction[m]+=int((oe<1)==(t<1) and (oo<0)==(to<0))
                cells+=1
        print('SUMMARY '+ ' '.join(f'{m}_joint_abs_error={score[m]:.6f} {m}_direction_matches={direction[m]}/{cells}' for m in MODELS))
    raise SystemExit('intentional diagnostic stop')

if __name__=='__main__':main()
