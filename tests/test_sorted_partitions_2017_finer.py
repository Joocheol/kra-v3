#!/usr/bin/env python3
import csv, gzip, math, unittest
from collections import Counter
import numpy as np

DATA='데이터/trifecta_feasible_sets.csv.gz'
LIMIT=1_000_000
CAP=LIMIT+1
MAXT=1200
MAXV=800

# Fast sufficient lower bound table.
bp=[[0]*(MAXT+1) for _ in range(MAXV+1)]
for v in range(MAXV+1): bp[v][0]=1
for v in range(1,MAXV+1):
    prev=bp[v-1]; cur=bp[v]
    for t in range(1,MAXT+1):
        cur[t]=prev[t]
        if t>=v: cur[t]=min(CAP,cur[t]+cur[t-v])

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
    lo=max(0,lo); hi=min(k*u,hi)
    for r in range(lo,hi+1):
        a,t=divmod(r,k); v=u-a
        if v>=0 and t<=MAXT and bp[min(v,MAXV)][t]>=CAP:
            return True
    return False

def lower_ranges(lo,hi,ku):
    """Map interval to one or two ranges on lower half using symmetry."""
    lo=max(0,lo); hi=min(ku,hi); mid=ku//2
    if hi<=mid: return [(lo,hi)]
    if lo>mid: return [(ku-hi,ku-lo)]
    # Upper half maps back; overlap at mid for odd ku represents two distinct totals.
    return [(lo,mid),(ku-hi,ku-mid-1)]

def exact_interval_numpy(lo,hi,k,u):
    """Exact candidate count capped at 1,000,001 via partition DP.
    dp[c,s] counts partitions of s with exactly c parts using processed sizes.
    Transpose rectangle to keep the part-count dimension small.
    """
    ku=k*u
    ranges=[(a,b) for a,b in lower_ranges(lo,hi,ku) if a<=b]
    if not ranges:return 0
    target=max(b for a,b in ranges)
    kk=min(k,u); uu=max(k,u)
    dp=np.zeros((kk+1,target+1),dtype=np.int64)
    dp[0,0]=1
    for v in range(1,min(uu,target)+1):
        shift=v
        for c in range(1,kk+1):
            # Ascending c permits repeated use of the current part v.
            arr=dp[c,shift:] + dp[c-1,:target+1-shift]
            np.minimum(arr,CAP,out=dp[c,shift:])
    coeff=np.minimum(dp.sum(axis=0),CAP)
    total=0
    for a,b in ranges:
        # Sum in Python int to avoid any accidental int64 overflow; each coeff is capped.
        total += int(coeff[a:b+1].sum(dtype=np.int64))
        if total>LIMIT:return CAP
    return total

def buck(n):
    if n<=1000:return '<=1000'
    if n<=10000:return '1001-10000'
    if n<=100000:return '10001-100000'
    if n<=1000000:return '100001-1000000'
    return '>1000000'

class Final2017(unittest.TestCase):
 def test_final_bins(self):
  # sanity checks
  self.assertEqual(exact_interval_numpy(0,5,1,10),6)
  self.assertEqual(exact_interval_numpy(5,5,10,10),7)
  with gzip.open(DATA,'rt',encoding='utf-8',newline='') as fh:
   rows=[r for r in csv.DictReader(fh) if r['year']=='2017' and int(r['capped_cells'])>0]
  for label,rr in [('strict',[r for r in rows if r['strict_feasible']=='1']),('combined',rows)]:
   bins=Counter(); methods=Counter(); examples={b:[] for b in ['<=1000','1001-10000','10001-100000','100001-1000000','>1000000']}
   for r in rr:
    k=int(r['capped_cells']);u=int(r['cap_ticket_upper'])
    if r['strict_feasible']=='1':lo=int(r['feasible_residual_min']);hi=int(r['feasible_residual_max'])
    else:lo=int(r['relaxed_residual_min']);hi=int(r['relaxed_residual_max'])
    n=simple_count(lo,hi,k,u)
    if n is not None: methods['simple']+=1
    elif cert_million(lo,hi,k,u): n=CAP; methods['cert']+=1
    else: n=exact_interval_numpy(lo,hi,k,u); methods['numpy_exact']+=1
    b=buck(n); bins[b]+=1
    if len(examples[b])<5: examples[b].append((r['race_id'],n,k,u,lo,hi,int(r['sales_won'])))
   print('FINAL_FINE_2017',label)
   print('bins='+','.join(f'{b}:{bins[b]}' for b in ['<=1000','1001-10000','10001-100000','100001-1000000','>1000000']))
   print('methods='+','.join(f'{m}:{methods[m]}' for m in ['simple','cert','numpy_exact']))
   for b in examples:
    print('EXAMPLES',b)
    for x in examples[b]: print(' ',*x)
   self.assertEqual(sum(bins.values()),len(rr))
  self.fail('intentional diagnostic stop')
