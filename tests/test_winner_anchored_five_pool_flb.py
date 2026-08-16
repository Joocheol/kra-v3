#!/usr/bin/env python3
import csv, gzip, math, pathlib, unittest
from collections import defaultdict
from decimal import Decimal
import numpy as np

from analyze_cross_market import load_feasible, load_race_records, completed_trifecta, marginalize, _won
from analyze_masked_reconstruction import bounded_integer_projection
from check_coherence import load_month
from kra.feasible import displayed_ticket_interval

DATA=pathlib.Path('데이터')
TAILS=(0.10,0.20,0.40)
TARGETS=('win','quinella','exacta','trio','trifecta')
SCENARIOS=('residual_min','residual_mid','residual_max')


def load_anchor_truth():
    out={}
    with gzip.open(DATA/'winning_capped_payouts.csv.gz','rt',encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            if r['pool']!='trifecta' or not ('2022'<=r['race_date'][:4]<='2025'):
                continue
            if r.get('is_above_display_cap')!='1' or not r.get('ticket_count'):
                continue
            if r.get('ticket_inference_status') not in ('identified',''):
                continue
            combo=(int(r['first_no']),int(r['second_no']),int(r['third_no']))
            out[r['race_id']]={'combo':combo,'tickets':int(r['ticket_count']),'odds':float(r['actual_odds'])}
    return out


def anchored_completion(race, odds, info, scenario, anchor):
    active=sorted(set(race['horses'])-set(race.get('scratched') or []))
    expected={(a,b,c) for a in active for b in active for c in active if len({a,b,c})==3}
    if set(odds)!=expected: raise ValueError('support mismatch')
    sales=_won(race['sales']['삼쌍승식']); total=sales//100
    uncapped=[]; capped=[]; lo=[]; hi=[]; target=[]
    for combo,value in sorted(odds.items()):
        if float(value)==9999.9:
            capped.append(combo); continue
        cand=displayed_ticket_interval(sales,Decimal(str(value)))
        if not cand: raise ValueError('visible interval missing')
        uncapped.append(combo); lo.append(cand.start); hi.append(cand.stop-1); target.append(.73*total/float(value))
    residual=int(info[scenario]); y=int(anchor['tickets']); w=anchor['combo']
    if w not in capped: raise ValueError('anchor winner is not capped')
    if y<0 or y>info['cap_upper'] or y>residual: return None
    uncapped_counts=bounded_integer_projection(np.asarray(target),np.asarray(lo),np.asarray(hi),total-residual)
    other=[c for c in capped if c!=w]; rem=residual-y
    if rem<0 or rem>len(other)*info['cap_upper']: return None
    if other:
        other_counts=bounded_integer_projection(
            np.full(len(other),rem/len(other),dtype=float),
            np.zeros(len(other),dtype=np.int64),
            np.full(len(other),info['cap_upper'],dtype=np.int64),rem)
    else:
        if rem!=0: return None
        other_counts=np.asarray([],dtype=np.int64)
    shares={c:float(n)/total for c,n in zip(uncapped,uncapped_counts)}
    shares[w]=y/total
    shares.update((c,float(n)/total) for c,n in zip(other,other_counts))
    if not math.isclose(sum(shares.values()),1.0,abs_tol=1e-12): raise AssertionError('mass')
    return shares


def pools(tri):
    out=marginalize(tri); out['trifecta']=tri; return out


def realised_keys(race):
    arr=tuple((race.get('arrival') or [])[:3])
    if len(arr)!=3 or len(set(arr))!=3: raise ValueError('arrival')
    a,b,c=arr
    return {'win':a,'quinella':frozenset((a,b)),'exacta':(a,b),'trio':frozenset((a,b,c)),'trifecta':arr}


def tail_contrib(pool,key,frac):
    ordered=sorted(pool.items(),key=lambda kv:kv[1]) # smallest probability = longest shot
    k=max(1,int(math.ceil(frac*len(ordered))))
    chosen=dict(ordered[:k]); e=sum(chosen.values()); o=1.0 if key in chosen else 0.0
    return o,e


class WinnerAnchoredFivePool(unittest.TestCase):
    def test_anchor(self):
        races=load_race_records(DATA/'races.jsonl.gz'); feasible=load_feasible(DATA/'trifecta_feasible_sets.csv.gz')
        anchors=load_anchor_truth(); by_month={}
        print('WINNER_ANCHORED_FIVE_POOL_FLB')
        print(f'anchors_loaded={len(anchors)} strict_feasible={len(feasible)}')
        feas_by_s={s:0 for s in SCENARIOS}; exact_checks=[]
        # Pooled Rmid tail statistics before/after replacing eligible winner-capped races by anchored completions.
        agg={name:{t:[0.,0.] for t in TAILS} for name in ('base','anchor') for _ in [0]}
        # restructure per target
        agg={name:{target:{t:[0.,0.] for t in TAILS} for target in TARGETS} for name in ('base','anchor')}
        changed=0; used_anchor=0
        for i,rid in enumerate(sorted(feasible),1):
            race=races[rid]; month=race['date'][:7]
            if month not in by_month: by_month[month]=load_month(DATA,month)
            market=by_month[month].get(rid)
            if market is None or not market['trifecta']: continue
            base=completed_trifecta(race,market['trifecta'],feasible[rid],'residual_mid')
            anchored=base; a=anchors.get(rid)
            if a:
                for s in SCENARIOS:
                    z=anchored_completion(race,market['trifecta'],feasible[rid],s,a)
                    if z is not None: feas_by_s[s]+=1
                z=anchored_completion(race,market['trifecta'],feasible[rid],'residual_mid',a)
                if z is not None:
                    anchored=z; used_anchor+=1
                    exact_checks.append((rid,a['tickets'],int(round(anchored[a['combo']]*( _won(race['sales']['삼쌍승식'])//100 ))),a['odds']))
                    if any(abs(anchored[k]-base[k])>1e-15 for k in base): changed+=1
            keys=realised_keys(race); bp=pools(base); ap=pools(anchored)
            for target in TARGETS:
                for t in TAILS:
                    bo,be=tail_contrib(bp[target],keys[target],t); ao,ae=tail_contrib(ap[target],keys[target],t)
                    agg['base'][target][t][0]+=bo; agg['base'][target][t][1]+=be
                    agg['anchor'][target][t][0]+=ao; agg['anchor'][target][t][1]+=ae
        print('ANCHOR_FEASIBILITY '+','.join(f'{s}={feas_by_s[s]}' for s in SCENARIOS))
        print(f'Rmid_anchors_used={used_anchor} changed_races={changed}')
        for rid,y,y2,od in exact_checks[:10]: print(f'ANCHOR_EXAMPLE race={rid} actual_odds={od:.1f} fixed_tickets={y} recovered={y2}')
        print('target,tail,base_OE,anchored_OE,delta,base_E,anchored_E')
        max_delta=0.0
        for target in TARGETS:
            for t in TAILS:
                bo,be=agg['base'][target][t]; ao,ae=agg['anchor'][target][t]
                b=bo/be; a=ao/ae; d=a-b; max_delta=max(max_delta,abs(d))
                print(f'{target},{t:.2f},{b:.6f},{a:.6f},{d:+.6f},{be:.6f},{ae:.6f}')
        print(f'MAX_ABS_OE_DELTA={max_delta:.6f}')
        self.assertGreaterEqual(len(anchors),40)
        self.assertEqual(used_anchor,len(anchors))
        self.assertTrue(all(y==y2 for _,y,y2,_ in exact_checks))
        self.fail('intentional diagnostic stop after output')
