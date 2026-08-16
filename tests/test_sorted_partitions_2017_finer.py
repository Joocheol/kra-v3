#!/usr/bin/env python3
import csv
import gzip
import math
import unittest
from collections import Counter

DATA = "데이터/trifecta_feasible_sets.csv.gz"


def comb_cap(n, k, cap=1_000_001):
    v = math.comb(n, k)
    return min(v, cap)


def simple_count(lo, hi, k, u, cap=1_000_001):
    lo=max(0,lo); hi=min(k*u,hi)
    if lo>hi: return 0
    if lo==0 and hi==k*u:
        return comb_cap(k+u,k,cap)
    if k==1:
        return hi-lo+1
    if u==1:
        return hi-lo+1
    if k==2:
        s=0
        for r in range(lo,hi+1):
            s += max(0, r//2 - max(0,r-u) + 1)
            if s>=cap: return cap
        return s
    if u==2:
        # vectors consist of a twos, b ones, and zeros; 2a+b=r, a+b<=k
        s=0
        for r in range(lo,hi+1):
            amin=max(0,r-k)
            amax=min(k,r//2)
            if amax>=amin: s += amax-amin+1
            if s>=cap: return cap
        return s
    return None


class Structure2017(unittest.TestCase):
    def test_structure(self):
        with gzip.open(DATA,"rt",encoding="utf-8",newline="") as fh:
            rows=[r for r in csv.DictReader(fh) if r["year"]=="2017" and int(r["capped_cells"])>0]
        strict=[r for r in rows if r["strict_feasible"]=="1"]
        print("STRUCTURE_2017")
        for label, rr in [("strict",strict),("combined",rows)]:
            cats=Counter(); unresolved=[]; known_bins=Counter()
            for r in rr:
                k=int(r["capped_cells"]); u=int(r["cap_ticket_upper"])
                if r["strict_feasible"]=="1":
                    lo=int(r["feasible_residual_min"]); hi=int(r["feasible_residual_max"])
                else:
                    lo=int(r["relaxed_residual_min"]); hi=int(r["relaxed_residual_max"])
                if lo<=0 and hi>=k*u: cats["full"]+=1
                elif k==1: cats["k1"]+=1
                elif k==2: cats["k2"]+=1
                elif u<=2: cats["u<=2"]+=1
                else:
                    cats["hard"]+=1
                    unresolved.append((r["race_id"],k,u,lo,hi,int(r["sales_won"])))
                n=simple_count(lo,hi,k,u)
                if n is not None:
                    if n<=1000: b="<=1000"
                    elif n<=10000: b="1001-10000"
                    elif n<=100000: b="10001-100000"
                    elif n<=1000000: b="100001-1000000"
                    else: b=">1000000"
                    known_bins[b]+=1
            print(label+"_cats="+",".join(f"{x}:{cats[x]}" for x in ["full","k1","k2","u<=2","hard"]))
            print(label+"_known_bins="+",".join(f"{x}:{known_bins[x]}" for x in ["<=1000","1001-10000","10001-100000","100001-1000000",">1000000"]))
            print(label+f"_hard={len(unresolved)}")
            for x in unresolved[:40]: print("HARD",*x)
        self.fail("intentional diagnostic stop")
