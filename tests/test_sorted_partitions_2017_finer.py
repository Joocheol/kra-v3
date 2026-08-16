#!/usr/bin/env python3
import csv, gzip, math, unittest
from collections import Counter

DATA='데이터/trifecta_feasible_sets.csv.gz'
LIMIT=1_000_000
CAP=LIMIT+1
MAXT=1200
MAXV=800

# bp[v][t] = number of partitions of t with largest part <= v, capped.
bp=[[0]*(MAXT+1) for _ in range(MAXV+1)]
for v in range(MAXV+1): bp[v][0]=1
for v in range(1,MAXV+1):
    prev=bp[v-1]; cur=bp[v]
    for t in range(1,MAXT+1):
        cur[t]=prev[t]
        if t>=v:
            cur[t]=min(CAP,cur[t]+cur[t-v])

def comb_cap(n,k): return min(CAP,math.comb(n,k))

def simple_count(lo,hi,k,u):
    lo=max(0,lo); hi=min(k*u,hi)
    if lo>hi:return 0
    if lo==0 and hi==k*u:return comb_cap(k+u,k)
    if k==1 or u==1:return hi-lo+1
    if k==2:
        s=0
        for r in range(lo,hi+1):
            s+=max(0,r//2-max(0,r-u)+1)
            if s>=CAP:return CAP
        return s
    if u==2:
        s=0
        for r in range(lo,hi+1):
            amin=max(0,r-k); amax=min(k,r//2)
            if amax>=amin:s+=amax-amin+1
            if s>=CAP:return CAP
        return s
    return None

def cert_million(lo,hi,k,u):
    """Sufficient condition: one fixed-total coefficient already exceeds 1m.
    For r=ak+t, add a to every component and inject every partition of t
    with largest part <= u-a. Since t<k, the part-count constraint cannot bind.
    """
    lo=max(0,lo); hi=min(k*u,hi)
    if lo>hi:return False,None
    for r in range(lo,hi+1):
        a,t=divmod(r,k); v=u-a
        if v<0: continue
        if t<=MAXT and min(v,MAXV)>=0 and bp[min(v,MAXV)][t]>=CAP:
            return True,(r,a,t,v)
    return False,None

def buck(n):
    if n<=1000:return '<=1000'
    if n<=10000:return '1001-10000'
    if n<=100000:return '10001-100000'
    if n<=1000000:return '100001-1000000'
    return '>1000000'

class Cert2017(unittest.TestCase):
 def test_cert(self):
  with gzip.open(DATA,'rt',encoding='utf-8',newline='') as fh:
   rows=[r for r in csv.DictReader(fh) if r['year']=='2017' and int(r['capped_cells'])>0]
  for label,rr in [('strict',[r for r in rows if r['strict_feasible']=='1']),('combined',rows)]:
   bins=Counter(); cert=0; unresolved=[]
   for r in rr:
    k=int(r['capped_cells']);u=int(r['cap_ticket_upper'])
    if r['strict_feasible']=='1':lo=int(r['feasible_residual_min']);hi=int(r['feasible_residual_max'])
    else:lo=int(r['relaxed_residual_min']);hi=int(r['relaxed_residual_max'])
    n=simple_count(lo,hi,k,u)
    if n is not None:
     bins[buck(n)]+=1;continue
    ok,w=cert_million(lo,hi,k,u)
    if ok:
     bins['>1000000']+=1;cert+=1
    else: unresolved.append((r['race_id'],k,u,lo,hi,int(r['sales_won'])))
   print('CERT_2017',label)
   print('bins_known_or_certified='+','.join(f'{b}:{bins[b]}' for b in ['<=1000','1001-10000','10001-100000','100001-1000000','>1000000']))
   print(f'certified_hard_gt1m={cert} unresolved={len(unresolved)}')
   for x in unresolved[:100]:print('UNRESOLVED',*x)
  self.fail('intentional diagnostic stop')
