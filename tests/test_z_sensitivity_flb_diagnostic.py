#!/usr/bin/env python3
import csv, gzip, pathlib, unittest
from collections import Counter
import numpy as np

DATA=pathlib.Path('데이터')


def load_rows():
    with gzip.open(DATA/'trifecta_feasible_sets.csv.gz','rt',encoding='utf-8',newline='') as f:
        return list(csv.DictReader(f))


def feasible_zero_counts(k,u,lo,hi):
    zs=[]
    for m in range(k+1):
        # m positive cells, z=k-m zeros; positive cells are integers 1..u.
        if m==0:
            ok=(lo<=0<=hi)
        else:
            ok=max(lo,m) <= min(hi,m*u)
        if ok: zs.append(k-m)
    return zs


def outcome_capped_by_race():
    out={}
    with gzip.open(DATA/'outcome_robustness.csv.gz','rt',encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            if r['model']!='trifecta_uniform_fractional': continue
            out[r['race_id']]=int(r['outcome_capped'])
    return out


class ZSensitivity(unittest.TestCase):
    def test_z_ranges_and_flb_invariance(self):
        rows=[r for r in load_rows() if int(r['capped_cells'])>0 and r['strict_feasible']=='1']
        print('Z_SENSITIVITY_CAPPED_STRICT')
        for label,subset in [
            ('2017',[r for r in rows if r['year']=='2017']),
            ('2022-2025',[r for r in rows if '2022'<=r['year']<='2025'])]:
            widths=[]; zlo=[]; zhi=[]; frac_lo=[]; frac_hi=[]; singleton=0; all_positive_possible=0; some_zero_forced=0
            for r in subset:
                k=int(r['capped_cells']); u=int(r['cap_ticket_upper']); lo=int(r['feasible_residual_min']); hi=int(r['feasible_residual_max'])
                zs=feasible_zero_counts(k,u,lo,hi)
                self.assertTrue(zs,(r['race_id'],k,u,lo,hi))
                a=min(zs); b=max(zs)
                zlo.append(a); zhi.append(b); widths.append(b-a+1); frac_lo.append(a/k); frac_hi.append(b/k)
                singleton += (a==b)
                all_positive_possible += (a==0)
                some_zero_forced += (a>0)
            q=lambda x,p: float(np.quantile(x,p)) if x else float('nan')
            print(f'SAMPLE {label} races={len(subset)} singleton_z={singleton} all_positive_possible={all_positive_possible} zero_forced={some_zero_forced}')
            print(f'  z_min q25={q(zlo,.25):.1f} med={q(zlo,.5):.1f} q75={q(zlo,.75):.1f}')
            print(f'  z_max q25={q(zhi,.25):.1f} med={q(zhi,.5):.1f} q75={q(zhi,.75):.1f}')
            print(f'  z_range_size q25={q(widths,.25):.1f} med={q(widths,.5):.1f} q75={q(widths,.75):.1f} p90={q(widths,.9):.1f}')
            print(f'  zero_fraction_min med={q(frac_lo,.5):.4f} q90={q(frac_lo,.9):.4f}; max med={q(frac_hi,.5):.4f} q90={q(frac_hi,.9):.4f}')

        # Main capped-set FLB is allocation-free: Q=R/total, independent of z and label assignment.
        outcomes=outcome_capped_by_race()
        flb=[r for r in rows if '2022'<=r['year']<='2025' and r['race_id'] in outcomes]
        print('MAIN_FLB_Z_INVARIANCE')
        for scenario in ('min','mid','max'):
            O=0; E=0.0
            for r in flb:
                lo=int(r['feasible_residual_min']); hi=int(r['feasible_residual_max']); total=int(r['total_tickets'])
                R=lo if scenario=='min' else hi if scenario=='max' else (lo+hi)//2
                O += outcomes[r['race_id']]
                E += R/total
                # enumerate z to explicitly verify Q does not move
                zs=feasible_zero_counts(int(r['capped_cells']),int(r['cap_ticket_upper']),lo,hi)
                qvals={R/total for _ in zs}
                self.assertEqual(len(qvals),1)
            print(f'  residual_{scenario}: races={len(flb)} observed={O} expected={E:.6f} O/E={O/E:.6f}')

        # Show representative widest z-identified sets in 2022-25.
        target=[]
        for r in rows:
            if not ('2022'<=r['year']<='2025'): continue
            k=int(r['capped_cells']); zs=feasible_zero_counts(k,int(r['cap_ticket_upper']),int(r['feasible_residual_min']),int(r['feasible_residual_max']))
            target.append((max(zs)-min(zs)+1,r['race_id'],k,int(r['cap_ticket_upper']),int(r['feasible_residual_min']),int(r['feasible_residual_max']),min(zs),max(zs)))
        for x in sorted(target,reverse=True)[:10]:
            print('WIDE_Z width=%d race=%s k=%d U=%d R=%d-%d z=%d-%d'%x)

        self.fail('intentional diagnostic stop after output')
