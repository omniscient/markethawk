import pytest

COST_COMMENT_BODY = """\
<!-- dark-factory-cost-report -->
<!-- cumulative: cost=7.197 in=310 out=123906 -->
## Dark Factory — Cost Report

**3 run(s) — Total: $7.197 (310 in / 123.9K out)**

### Run: 2026-06-04 12:42 UTC (plan, completed)

| Step | Model | In tokens | Out tokens | Cost | Duration |
|------|-------|-----------|------------|------|----------|
| parse-intent |  | 28 | 271 | $0.0138 | 6.4s |
| fetch-issue |  | 0 | 0 | $0 | 1.1s |
| plan |  | 38 | 56700 | $2.8727 | 24m 47s |
| **Subtotal** | | **66** | **56971** | **$2.8865** | |

### Run: 2026-06-04 15:17 UTC (implement, completed)

| Step | Model | In tokens | Out tokens | Cost | Duration |
|------|-------|-----------|------------|------|----------|
| implement |  | 45 | 20200 | $1.9607 | 7m 18s |
| validate |  | 12 | 7400 | $0.3274 | 4m 0s |
| **Subtotal** | | **57** | **27600** | **$2.2881** | |

### Run: 2026-06-04 17:05 UTC (fix, completed)

| Step | Model | In tokens | Out tokens | Cost | Duration |
|------|-------|-----------|------------|------|----------|
| implement |  | 187 | 40135 | $2.0224 | 8m 12s |
| **Subtotal** | | **187** | **40135** | **$2.0224** | |
"""


@pytest.fixture
def cost_comment():
    return COST_COMMENT_BODY
