PY := .venv/bin/python

# 각 단계는 이전 단계의 게이트가 열려야 실행된다.
# 게이트는 review/RESPONSE_*.md 의 완결성으로만 열린다.

.PHONY: help p0 p1 p2 p3 m status backlog check freeze

help:
	@echo "make check     프로세스 위생 + 동결 검증 (CI와 동일)"
	@echo "make freeze    동결 산출물만 재생성·검증"
	@echo "make p0        데이터 검증 → 비평"
	@echo "make p1        (P0 게이트) 탐색 → 비평"
	@echo "make p2        (P1 게이트) 아이디어 평가 → 비평"
	@echo "make p3        (P2 게이트) 사전분석계획 → 비평"
	@echo "make m M=M1    (P3 게이트) 확증 마일스톤 → 비평"
	@echo "make status    모든 게이트 상태"
	@echo ""
	@echo "2라운드:  make critique-P1 ROUND=2"

# ---------------------------------------------------------------- P0
p0:
	$(PY) analysis/p0_verify.py
	$(MAKE) critique-P0

critique-P0:
	$(PY) scripts/critique.py --phase P0 --round $(or $(ROUND),1) \
	  --input analysis/SPEC_P0.md REPORT_P0.md

gate-P0:
	@$(PY) scripts/gate.py --phase P0

# ---------------------------------------------------------------- P1
p1: gate-P0
	$(PY) analysis/p1_explore.py
	$(MAKE) critique-P1

critique-P1:
	$(PY) scripts/critique.py --phase P1 --round $(or $(ROUND),1) \
	  --input FACTS.md EXPLORATION_LOG.md \
	  --context REPORT_P0.md

gate-P1:
	@$(PY) scripts/gate.py --phase P1

# ---------------------------------------------------------------- P2
p2: gate-P1
	$(MAKE) critique-P2

critique-P2:
	$(PY) scripts/critique.py --phase P2 --round $(or $(ROUND),1) \
	  --input IDEAS.md --context FACTS.md

gate-P2:
	@$(PY) scripts/gate.py --phase P2

# ---------------------------------------------------------------- P3
p3: gate-P2
	$(MAKE) critique-P3

critique-P3:
	$(PY) scripts/critique.py --phase P3 --round $(or $(ROUND),1) \
	  --input PAP.md --context IDEAS.md EXPLORATION_LOG.md

gate-P3:
	@$(PY) scripts/gate.py --phase P3

# ---------------------------------------------------------------- 확증 마일스톤
m: gate-P3
	@test -n "$(M)" || (echo "usage: make m M=M1"; exit 1)
	$(PY) analysis/$(M)_*.py
	$(PY) scripts/critique.py --phase M --milestone $(M) --round $(or $(ROUND),1) \
	  --input analysis/SPEC_$(M).md analysis/REPORT_$(M).md \
	  --context PAP.md CLAIMS.md

gate-m:
	@test -n "$(M)" || (echo "usage: make gate-m M=M1"; exit 1)
	@$(PY) scripts/gate.py --phase M --milestone $(M)

# ---------------------------------------------------------------- 검사
check:
	$(PY) scripts/check_process.py
	$(PY) scripts/check_freeze.py --regenerate

freeze:
	$(PY) scripts/check_freeze.py --regenerate

status:
	@for p in P0 P1 P2 P3; do \
	  printf "%-4s " $$p; \
	  $(PY) scripts/gate.py --phase $$p >/dev/null 2>&1 \
	    && echo "OPEN" || echo "BLOCKED"; \
	done

backlog:
	@grep -c '^- \[' BACKLOG.md 2>/dev/null || echo 0
