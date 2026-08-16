#!/usr/bin/env python3
import csv, gzip, math, pathlib, unittest
from collections import defaultdict, Counter
import numpy as np

from kra.feasible import displayed_ticket_interval
from analyze_masked_reconstruction import bounded_integer_projection
from analyze_feasible_sets import load_races, _validated_trifecta_cell

DATA = pathlib.Path('데이터')
FEAS = DATA / 'trifecta_feasible_sets.csv.gz'
BINS = 100
BOOT = 50
RNG = np.random.default_rng(20260817)


def load_feasible():
    with gzip.open(FEAS, 'rt', encoding='utf-8', newline='') as f:
        return [r for r in csv.DictReader(f) if r['year'] == '2017']


def load_2017_odds(wanted):
    races=load_races(DATA/'races.jsonl.gz')
    out=defaultdict(list); seen=defaultdict(set)
    for path in sorted((DATA/'cells'/'page_key=3Both').glob('2017-*.csv.gz')):
        with gzip.open(path,'rt',encoding='utf-8',newline='') as f:
            for r in csv.DictReader(f):
                rid=r['race_id']
                if rid not in wanted: continue
                value=_validated_trifecta_cell(r,races[rid],seen[rid])
                if value is None or r['cell_raw']=='9999.9': continue
                out[rid].append(value)
    return out


def reconstruct_uncapped(sales, odds):
    mids=[]
    for d in odds:
        c=displayed_ticket_interval(sales,d)
        if not c: return None
        mids.append((c.start+c.stop-1)/2.0)
    return np.sort(np.rint(np.asarray(mids,float)).astype(np.int64))[::-1]


def race_profile(counts):
    J=len(counts); mean=float(np.mean(counts)); vals=[[] for _ in range(BINS)]
    for i,n in enumerate(counts):
        b=min(BINS-1,int(((i+0.5)/J)*BINS))
        vals[b].append(math.log((float(n)+0.5)/(mean+0.5)))
    row=np.full(BINS,np.nan)
    for b,v in enumerate(vals):
        if v: row[b]=float(np.median(v))
    good=np.flatnonzero(np.isfinite(row))
    if len(good)==0: raise ValueError('empty race profile')
    return np.interp(np.arange(BINS),good,row[good])


def aggregate_profile(rows):
    p=np.nanmedian(np.atleast_2d(np.asarray(rows,dtype=float)),axis=0)
    return np.minimum.accumulate(p)


def rank_scores(profile,J,k):
    return np.asarray([math.exp(float(profile[min(BINS-1,int(((i+0.5)/J)*BINS))])) for i in range(J-k,J)],float)


def allocate(profile,J,k,total,U=None):
    if k==0: return np.empty(0,dtype=np.int64)
    scores=rank_scores(profile,J,k); scores/=scores.sum()
    lo=np.zeros(k,dtype=np.int64); hi=np.full(k,total if U is None else U,dtype=np.int64)
    if hi.sum()<total: return None
    x=bounded_integer_projection(total*scores,lo,hi,total)
    return np.sort(x)[::-1]


def uniform_alloc(k,total,U=None):
    if k==0: return np.empty(0,dtype=np.int64)
    q,r=divmod(total,k); x=np.array([q+1]*r+[q]*(k-r),dtype=np.int64)
    if U is not None and len(x) and x[0]>U: return None
    return x


def metrics(truth,pred):
    e=np.asarray(pred)-np.asarray(truth)
    return float(np.mean(np.abs(e))),float(np.sqrt(np.mean((np.log1p(pred)-np.log1p(truth))**2)))


class EmpiricalRank2017(unittest.TestCase):
    def test_rank_profile(self):
        rows=load_feasible(); capped=[r for r in rows if int(r['capped_cells'])>0]
        strict_capped=[r for r in capped if r['strict_feasible']=='1']
        clean=[r for r in rows if int(r['capped_cells'])==0 and int(r['rounding_incompatible_cells'])==0]
        odds=load_2017_odds({r['race_id'] for r in clean})
        reconstructed=[]
        for r in clean:
            rid=r['race_id']; J=int(r['expected_combinations'])
            if len(odds.get(rid,[]))!=J: continue
            x=reconstruct_uncapped(int(r['sales_won']),odds[rid])
            if x is not None: reconstructed.append((rid,x))
        reconstructed.sort()
        print('PRE_PROFILE',f'rows={len(rows)} capped={len(capped)} strict_capped={len(strict_capped)} clean={len(clean)} grids={len(odds)} reconstructed={len(reconstructed)}')
        self.assertGreater(len(reconstructed),100)
        train=[z for i,z in enumerate(reconstructed) if i%5!=0]; valid=[z for i,z in enumerate(reconstructed) if i%5==0]
        train_profiles=[race_profile(x) for _,x in train]; profile=aggregate_profile(train_profiles)
        print('EMPIRICAL_RANK_2017')
        print(f'clean_usable={len(reconstructed)} train={len(train)} valid={len(valid)} strict_capped={len(strict_capped)}')
        for frac in (0.20,0.40,0.60):
            pm=[]; um=[]
            for _,truth_all in valid:
                J=len(truth_all); k=max(1,int(round(frac*J))); truth=truth_all[J-k:]; total=int(truth.sum())
                pm.append(metrics(truth,allocate(profile,J,k,total))); um.append(metrics(truth,uniform_alloc(k,total)))
            pmae=np.mean([x[0] for x in pm]); umae=np.mean([x[0] for x in um]); prmse=np.mean([x[1] for x in pm]); urmse=np.mean([x[1] for x in um])
            print(f'VALID frac={frac:.2f} profile_MAE={pmae:.4f} uniform_MAE={umae:.4f} MAE_gain={(umae-pmae)/umae*100:.2f}% profile_logRMSE={prmse:.5f} uniform_logRMSE={urmse:.5f} log_gain={(urmse-prmse)/urmse*100:.2f}%')

        arr=np.asarray(train_profiles); boot=[]
        for _ in range(BOOT):
            idx=RNG.integers(0,len(arr),len(arr)); boot.append(aggregate_profile(arr[idx]))
        unique_bins=Counter(); spread=[]; zero_base=[]; l1_uniform=[]; usable=0; examples=[]
        for r in strict_capped:
            k=int(r['capped_cells']); J=int(r['expected_combinations']); U=int(r['cap_ticket_upper']); lo=int(r['feasible_residual_min']); hi=int(r['feasible_residual_max']); R=(lo+hi)//2
            base=allocate(profile,J,k,R,U)
            if base is None: continue
            usable+=1; sims=[]; hashes=set()
            for bp in boot:
                z=allocate(bp,J,k,R,U)
                if z is not None: sims.append(z); hashes.add(z.tobytes())
            if sims:
                A=np.vstack(sims); spread.append(float(np.mean(np.quantile(A,.95,axis=0)-np.quantile(A,.05,axis=0)))); d=len(hashes)
                unique_bins['<=5' if d<=5 else '6-10' if d<=10 else '11-25' if d<=25 else '26-50']+=1
            zero_base.append(int(np.sum(base==0))); uni=uniform_alloc(k,R,U)
            if uni is not None and R>0: l1_uniform.append(float(np.sum(np.abs(base-uni))/R))
            if len(examples)<8: examples.append((r['race_id'],k,U,lo,hi,int(np.sum(base==0)),int(base[0]),float(np.median(base)),len(hashes)))
        q=lambda v,p: float(np.quantile(v,p)) if v else float('nan')
        print(f'ACTUAL usable={usable}')
        print('BOOT_UNIQUE '+','.join(f'{b}:{unique_bins[b]}' for b in ['<=5','6-10','11-25','26-50']))
        print(f'BOOT_MEAN_CELL_90WIDTH q25={q(spread,.25):.3f} median={q(spread,.5):.3f} q75={q(spread,.75):.3f}')
        print(f'BASE_ZERO_CELLS q25={q(zero_base,.25):.1f} median={q(zero_base,.5):.1f} q75={q(zero_base,.75):.1f}')
        print(f'PROFILE_vs_UNIFORM_normalized_L1 q25={q(l1_uniform,.25):.4f} median={q(l1_uniform,.5):.4f} q75={q(l1_uniform,.75):.4f}')
        for e in examples: print('EXAMPLE race=%s k=%d U=%d R=%d-%d zeros=%d max=%d median=%.1f boot_unique=%d'%e)
        self.assertEqual(len(strict_capped),1660)
        self.fail('intentional temporary diagnostic stop after output')
