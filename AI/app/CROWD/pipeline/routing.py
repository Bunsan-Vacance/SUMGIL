"""가용성별 예측기 라우팅 정책 — 순수 함수(197 B-1).

`Predictor`는 이미 플러그인(`predictor.py`)이지만 "어떤 상황에 어떤 kind를 쓰나"는 코드 어디에도
없어서 `predict_day`에 if-else로 박으면 145의 다른 축(노선·군집)을 켤 때 구조를 다시 잡아야 하고
BE 계약도 다시 바뀐다. 그래서 규칙을 데이터(`POLICY: list[Rule]`)로 두고, 매칭은 이 모듈의
순수 함수(`select`)가 한다. 예측기 인스턴스는 여기서 만들지 않는다 — 무거운 import(torch 등)를
피하기 위해서고, 실제 생성은 호출자(`batch_predict.py`)가 필요할 때만 한다.

가용성 4단은 `masking.SCENARIOS`(`full`/`d7_only`/`d1_only`/`no_lag`)와 같은 이름을 쓴다 — 학습 때
쓰는 결측 시나리오와 서빙 때 실제로 마주치는 이력 상태가 같은 축이기 때문이다.

145 `family-check/RESULTS.md` 8절 판정(2026-09-16 확정, 휴일 예외 없음):

| 이력 상태 | 예측기 | 근거 |
| --- | --- | --- |
| `full` | LightGBM | GRU가 −2.92/−2.03%p 열세(1호선·5호선 슬라이스가 교체 기준을 깬다) |
| `d1_only`/`d7_only` | GRU(dl) | GRU가 +10.56~+25.51%p 우위 |
| `no_lag` | GRU(dl) | GRU가 +38.86/+44.18%p 우위(정확도 우위가 아니라 LightGBM의 −36.6/−40.7%p 붕괴 회피) |
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


def availability(lag1d_available: bool, lag7d_available: bool) -> str:
    """전날·1주 전 실측 유무 → `masking.SCENARIOS` 키(`full`/`d1_only`/`d7_only`/`no_lag`)."""
    if lag1d_available and lag7d_available:
        return "full"
    if lag1d_available and not lag7d_available:
        return "d1_only"
    if not lag1d_available and lag7d_available:
        return "d7_only"
    return "no_lag"


@dataclass(frozen=True)
class Rule:
    """라우팅 규칙 하나. `pred`가 고를 예측기 kind, 나머지는 조건(생략 시 무조건 일치).

    조건 필드가 여럿이면 `select`가 **명시된 조건 개수가 많은 규칙을 우선**한다 — 지금은 `avail`만
    쓰지만, 노선·군집 규칙(주석 처리된 예시 참고)을 켜는 순간 같은 목록 안에서 공존해야 하기 때문에
    나머지 필드도 미리 정의해 둔다.
    """

    pred: str
    avail: str | None = None
    line: str | None = None
    day_type: str | None = None
    group: str | None = None


# 활성 정책은 가용성 축만이다 — 오늘 한 표는 예측기가 하나로 배정된다. 그래도 Rule이 행 단위
# 조건(line·day_type·group)을 받을 수 있어야, 노선 규칙을 켜는 순간 두 모델을 섞어야 할 때
# 구조를 다시 잡지 않는다.
POLICY: list[Rule] = [
    Rule(avail="full", pred="lightgbm"),
    Rule(avail="d1_only", pred="dl"),
    Rule(avail="d7_only", pred="dl"),
    Rule(avail="no_lag", pred="dl"),
    # 부원(비활성) — 근거는 있으나 미검증. 켜기 전 논의 I-1(원인 규명)이 선행.
    # Rule(avail="full", line="1호선", pred="linear"),
    #   근거: stat-model-check 3절 ols_series − lightgbm RMSE +15.48/+17.45%p [하한 +13.65/+15.01]
    #         family-check 3절 GRU는 같은 1호선에서 −9.93/−9.32%p (반대 방향)
    # Rule(avail="full", group="cluster_shape", pred="lightgbm_cluster"),
    #   근거: split-tuning-check·compare_features — 모양 군집 승차 +0.64 [+0.27] (하차는 구분 불가)
]


def _specificity(rule: Rule) -> int:
    return sum(1 for v in (rule.avail, rule.line, rule.day_type, rule.group) if v is not None)


def _matches(
    rule: Rule,
    *,
    avail: str | None,
    line: str | None,
    day_type: str | None,
    group: str | None,
) -> bool:
    if rule.avail is not None and rule.avail != avail:
        return False
    if rule.line is not None and rule.line != line:
        return False
    if rule.day_type is not None and rule.day_type != day_type:
        return False
    return rule.group is None or rule.group == group


def match_rule(
    rules: list[Rule],
    *,
    avail: str,
    line: str | None = None,
    day_type: str | None = None,
    group: str | None = None,
) -> Rule:
    """조건에 맞는 규칙 중 가장 구체적인 것. 동률이면 목록에서 앞선 것. 매칭 없으면 `ValueError`."""
    best: Rule | None = None
    best_specificity = -1
    for rule in rules:
        if not _matches(rule, avail=avail, line=line, day_type=day_type, group=group):
            continue
        specificity = _specificity(rule)
        if specificity > best_specificity:  # 엄격한 '>'라 동률이면 먼저 온 규칙이 유지된다
            best = rule
            best_specificity = specificity
    if best is None:
        raise ValueError(
            f"라우팅 규칙 매칭 없음: avail={avail!r} line={line!r} day_type={day_type!r} "
            f"group={group!r} — POLICY에 해당 조건을 받는 규칙이 없다"
        )
    return best


def select(
    rules: list[Rule],
    *,
    avail: str,
    line: str | None = None,
    day_type: str | None = None,
    group: str | None = None,
) -> str:
    """매칭된 규칙의 예측기 kind. 우선순위·실패 규약은 `match_rule` 참고."""
    return match_rule(rules, avail=avail, line=line, day_type=day_type, group=group).pred


def describe_policy(rules: list[Rule]) -> list[dict]:
    """규칙 목록을 메타·문서용으로 직렬화(각 규칙 = 필드 전부를 담은 dict)."""
    return [asdict(rule) for rule in rules]
