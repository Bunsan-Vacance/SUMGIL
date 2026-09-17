"""197 B-1 — 가용성 판정·라우팅 정책 순수 함수 테스트.

`routing.py`는 무거운 의존성이 없는 순수 로직이라 예측기를 만들지 않고도 우선순위·실패 규약을
검증할 수 있다. `POLICY`가 실제로 4가지 가용성을 전부 커버하는지(매칭 실패로 배치가 멈추지
않는지)도 여기서 본다.
"""

from __future__ import annotations

import pytest

from app.CROWD.pipeline.masking import SCENARIOS
from app.CROWD.pipeline.routing import (
    POLICY,
    Rule,
    availability,
    describe_policy,
    match_rule,
    select,
)


# ── availability ──
def test_availability_full_when_both_lags_present():
    assert availability(True, True) == "full"


def test_availability_d1_only_when_lag7d_missing():
    assert availability(True, False) == "d1_only"


def test_availability_d7_only_when_lag1d_missing():
    assert availability(False, True) == "d7_only"


def test_availability_no_lag_when_both_missing():
    assert availability(False, False) == "no_lag"


def test_availability_names_match_masking_scenarios():
    for lag1d in (True, False):
        for lag7d in (True, False):
            assert availability(lag1d, lag7d) in SCENARIOS


# ── select / match_rule 우선순위 ──
def test_select_matches_simple_avail_rule():
    rules = [Rule(avail="full", pred="lightgbm"), Rule(avail="no_lag", pred="dl")]
    assert select(rules, avail="full") == "lightgbm"
    assert select(rules, avail="no_lag") == "dl"


def test_select_prefers_more_specific_rule():
    rules = [
        Rule(avail="full", pred="lightgbm"),
        Rule(avail="full", line="1호선", pred="linear"),
    ]
    # 명시 조건 2개(avail+line)인 규칙이 조건 1개(avail만)인 규칙을 이긴다.
    assert select(rules, avail="full", line="1호선") == "linear"
    # 노선이 다르면 구체 규칙이 매칭 안 되니 일반 규칙으로 떨어진다.
    assert select(rules, avail="full", line="2호선") == "lightgbm"


def test_select_ties_break_by_list_order():
    rules = [
        Rule(avail="full", pred="first"),
        Rule(avail="full", pred="second"),
    ]
    # 명시 조건 개수가 같으면(둘 다 avail 1개) 목록에서 먼저 나온 규칙이 이긴다.
    assert select(rules, avail="full") == "first"


def test_select_raises_when_no_rule_matches():
    rules = [Rule(avail="full", pred="lightgbm")]
    with pytest.raises(ValueError, match="라우팅 규칙 매칭 없음"):
        select(rules, avail="no_lag")


def test_match_rule_returns_the_full_rule_not_just_pred():
    rules = [Rule(avail="d1_only", pred="dl")]
    rule = match_rule(rules, avail="d1_only")
    assert rule == Rule(avail="d1_only", pred="dl")


# ── describe_policy ──
def test_describe_policy_serializes_all_fields():
    rules = [Rule(avail="full", pred="lightgbm")]
    described = describe_policy(rules)
    assert described == [
        {"pred": "lightgbm", "avail": "full", "line": None, "day_type": None, "group": None}
    ]


# ── POLICY(실제 활성 정책) ──
def test_policy_covers_all_four_availability_levels():
    """가용성 4단 어느 것으로 불러도 매칭이 있어야 한다 — 없으면 배치가 ValueError로 멈춘다."""
    for avail in SCENARIOS:
        # 예외 없이 하나를 고를 수 있어야 한다.
        kind = select(POLICY, avail=avail)
        assert kind in ("lightgbm", "dl")


def test_policy_matches_145_masking_check_decision():
    """145 후속 `masking-check/RESULTS.md` 14절 — 결정 "(나) 혼합 유지, 표 수정".

    마스킹 학습 LightGBM이 `d7_only`·`no_lag`의 배포 LightGBM 붕괴를 없애 GRU보다 나아졌다
    (`d7_only` +12.0/+13.8%p, `no_lag` RMSE 동등). `d1_only`만 GRU가 +5.6~+9.0%p 우위라 그대로다
    (197 당시는 결손·전무 셋 모두 GRU였다).
    """
    assert select(POLICY, avail="full") == "lightgbm"
    assert select(POLICY, avail="d1_only") == "dl"
    assert select(POLICY, avail="d7_only") == "lightgbm"
    assert select(POLICY, avail="no_lag") == "lightgbm"
