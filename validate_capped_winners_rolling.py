#!/usr/bin/env python3
"""Rolling-origin external validation on frozen 2023--2025 capped winners.

Official winning payouts are outcome-selected and never used for fitting.  For
each target year y in 2023, 2024, 2025, cross-pool allocation coefficients are
estimated only from artificial masking in real capped races from earlier years
(2022..y-1), then applied to official capped winners in year y.

The goal is not to claim winner-selected accuracy as representative of all cap
cells.  It is a larger external stress test of whether point allocation improves
over uniform when the training regime and chronology are correct.
"""
from __future__ import annotations

import csv
import gzip
import pathlib
import statistics

from analyze_cross_market import load_feasible, load_race_records
from analyze_masked_reconstruction import load_cross_pool_odds, load_grids
from analyze_capped_regime_masking import build_experiment, fit_coefficients
from check_coherence import load_month
from validate_capped_regime_winners_all8 import (
    CROSS_COLUMNS, EXACTA_COL, probabilities_for_caps, project,
)

DATA=pathlib.Path("데이터")
THRESHOLD=7000.0
YEARS=(2023,2024,2025)


def load_truth_all(path:pathlib.Path):
    out=[]
    with gzip.open(path,"rt",encoding="utf-8",newline="") as fh:
        for row in csv.DictReader(fh):
            year=int(row["race_date"][:4])
            if (
                row["pool"]=="trifecta" and year in YEARS and row["ticket_count"]
                and row["is_above_display_cap"]=="1"
            ):
                out.append({
                    "year":year,"race_id":row["race_id"],
                    "combo":(int(row["first_no"]),int(row["second_no"]),int(row["third_no"])),
                    "actual_odds":float(row["actual_odds"]),"truth":int(row["ticket_count"]),
                })
    return out


def main()->int:
    races=load_race_records(DATA/"races.jsonl.gz")
    feasible=load_feasible(DATA/"trifecta_feasible_sets.csv.gz")
    ids={rid for rid,info in feasible.items() if int(info["capped_cells"])>0}
    grids=load_grids(DATA,races,ids); cross=load_cross_pool_odds(DATA,ids)
    truths=load_truth_all(DATA/"winning_capped_payouts.csv.gz")
    by_month={}; all_rows=[]

    print("target_year,train_years,train_races,rich_exacta,rich_trio,exacta_only,official_n,uniform_MAE,model_MAE,uniform_MdAPE,model_MdAPE,model_better,scenario_coverage")
    for year in YEARS:
        train=[]
        for rid in sorted(ids):
            ry=int(races[rid]["date"][:4])
            if not (2022<=ry<year):continue
            e=build_experiment(races[rid],grids[rid],cross.get(rid,{}),THRESHOLD)
            if e is not None:train.append(e)
        if not train:raise ValueError(f"no training for {year}")
        rich,_=fit_coefficients(train,CROSS_COLUMNS)
        ex,_=fit_coefficients(train,EXACTA_COL)

        target=[t for t in truths if t["year"]==year]
        rows=[]
        for t in target:
            rid=t["race_id"]; race=races[rid]; month=race["date"][:7]
            if month not in by_month:by_month[month]=load_month(DATA,month)
            market=by_month[month][rid]; info=feasible[rid]
            odds=market["trifecta"]; hidden=sorted(c for c,v in odds.items() if float(v)==9999.9)
            if t["combo"] not in hidden:raise ValueError(f"{rid}: truth not capped")
            idx=hidden.index(t["combo"])
            p,method=probabilities_for_caps(race,market,rich,ex)
            uniform_p=p*0+1/len(p)
            model_mid=int(project(info,p,"residual_mid")[idx])
            uniform_mid=int(project(info,uniform_p,"residual_mid")[idx])
            preds=[int(project(info,p,s)[idx]) for s in ("residual_min","residual_mid","residual_max")]
            y=int(t["truth"]); cover=int(min(preds)<=y<=max(preds))
            rows.append((rid,y,uniform_mid,model_mid,method,cover,t["actual_odds"]))
            all_rows.append((year,*rows[-1]))

        ua=[abs(u-y) for _,y,u,_,_,_,_ in rows]; ma=[abs(m-y) for _,y,_,m,_,_,_ in rows]
        ur=[abs(u-y)/y for _,y,u,_,_,_,_ in rows]; mr=[abs(m-y)/y for _,y,_,m,_,_,_ in rows]
        print(
            f"{year},2022-{year-1},{len(train)},{rich[0]:.6f},{rich[1]:.6f},{ex[0]:.6f},"
            f"{len(rows)},{statistics.mean(ua):.3f},{statistics.mean(ma):.3f},"
            f"{statistics.median(ur):.4%},{statistics.median(mr):.4%},"
            f"{sum(m<u for m,u in zip(ma,ua))}/{len(rows)},{sum(r[5] for r in rows)}/{len(rows)}"
        )

    print("\n# pooled rolling-origin details")
    print("year,race_id,actual_odds,true_tickets,uniform_mid,model_mid,method,scenario_coverage")
    for year,rid,y,u,m,method,cover,payout in all_rows:
        print(f"{year},{rid},{payout:.1f},{y},{u},{m},{method},{cover}")
    if all_rows:
        ua=[abs(u-y) for _,_,y,u,_,_,_,_ in all_rows]; ma=[abs(m-y) for _,_,y,_,m,_,_,_ in all_rows]
        ur=[abs(u-y)/y for _,_,y,u,_,_,_,_ in all_rows]; mr=[abs(m-y)/y for _,_,y,_,m,_,_,_ in all_rows]
        print(
            f"POOLED n={len(all_rows)} uniform_MAE={statistics.mean(ua):.3f} model_MAE={statistics.mean(ma):.3f} "
            f"uniform_MdAPE={statistics.median(ur):.4%} model_MdAPE={statistics.median(mr):.4%} "
            f"model_better={sum(m<u for m,u in zip(ma,ua))}/{len(all_rows)} "
            f"scenario_coverage={sum(r[6] for r in all_rows)}/{len(all_rows)}"
        )
    return 0

if __name__=="__main__":
    raise SystemExit(main())
