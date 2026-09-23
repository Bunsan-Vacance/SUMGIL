"""331 — `RuleStrategy` vs `AgentStrategy` 기준선 비교 하네스.

같은 `AgentContext` 표본 집합(`build_samples.py`가 만든 `samples/samples.json`)에 두 전략을
그대로 태워 선택 일치율·가드 탈락 사유·reason 길이·토큰·지연을 기록한다. 이 수치가 토큰
최적화(요약 압축·후보 상한·max_tokens)의 **기준선**이다(`plans/TIME-331-harness-plan.md`).

`AI/CLAUDE.md` 모델 비교 하드 룰을 그대로 적용한다 — 두 전략이 완전히 같은 표본·같은
`ScoreWeights`(폴백)·같은 `LlmBudget` 상한을 보게 한 뒤에만 "비교"라고 부른다. 표본마다
`AgentStrategy`·`LlmBudget`을 새로 만든다 — 실제 서비스에서도 세션(=한 번의 재안내 판단)마다
예산이 새로 시작하는 것과 같은 전제다(`llm_budget.py` 모듈 docstring).

## 일치율을 읽을 때 주의

`AgentStrategy.decide()`는 가드에 하나라도 걸리면 `fallback`(=`RuleStrategy`, 같은 가중치)의
결과를 **그대로** 돌려준다. 그래서 가드 탈락이 난 표본과 "후보 1개라 LLM을 안 부른" 표본은
`agent_index`가 애초에 `rule_index`와 같은 값이 나올 수밖에 없다 — 이 표본들의 "일치"는 두
판단이 실제로 같은 답에 도달했다는 뜻이 아니라 **에이전트가 규칙으로 대체됐다는 뜻**이다.
`match_rate`가 높다고 "LLM이 규칙과 대체로 같은 후보를 고른다"고 읽으면 안 되고, `recommended_by
== AGENT`인 표본만 따로 봐야 실제 판단 일치율을 알 수 있다 — 아래 출력·`RESULTS.md` 둘 다 이
구분(`n_llm_accepted`)을 남긴다.

`--llm fake`의 가짜 클라이언트는 규칙의 선택을 그대로 따라 하고 이유도 후보 설명
(`describe_candidate`)에서 그대로 인용하므로, 환각 검사를 항상 통과해 `match_rate`가 100%에
가깝게 나오는 것이 **정상**이다 — 이건 "에이전트가 규칙에 동의한다"는 신호가 아니라 배관
(파싱·가드·집계)이 제대로 돈다는 스모크 신호다. 실제 판단 차이를 보려면 `--llm real`이 필요하다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[3]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from samples_io import from_json, read_samples  # noqa: E402

from app.TIME.context import AgentContext  # noqa: E402
from app.TIME.llm import LlmClient, LlmOutcome, LlmResult, settings_client  # noqa: E402
from app.TIME.llm_budget import LlmBudget  # noqa: E402
from app.TIME.strategy import (  # noqa: E402
    RECOMMENDED_BY_AGENT,
    AgentStrategy,
    RerouteProposal,
    RuleStrategy,
    ScoreWeights,
    _sentence_count,  # 같은 정규식으로 재는 문장 수 — 별도 구현을 두면 TOO_LONG 판정과 어긋난다
    describe_candidate,
)

DEFAULT_SAMPLES = _HERE.parent / "samples" / "samples.json"
FAKE_MODEL_NAME = "fake-rule-echo"


# ── fake 클라이언트 ──


@dataclass
class FakeLlmClient:
    """`LlmClient` 프로토콜을 만족하는 가짜 게이트웨이. **네트워크를 전혀 쓰지 않는다.**

    표본 하나에 묶여 있다(`ctx`·`weights`를 생성자에서 받는다) — 규칙 전략의 선택을 그대로
    따라 하고, `reason`은 그 후보의 `describe_candidate()` 요약에서 번호만 뗀 문장을 그대로
    인용한다. 두 가지 다 프롬프트에 실제로 보여준 값이라 `AgentStrategy`의 환각 검사
    (`_allowed_numbers`·이름 검사)를 항상 통과한다 — fake 모드의 목적은 "LLM이 다르게 판단하는
    경우"가 아니라 파싱·가드·집계 배관을 실제 게이트웨이 없이 스모크하는 것이기 때문이다.
    """

    ctx: AgentContext
    weights: ScoreWeights
    delay_ms: float = 0.0
    calls: int = field(default=0, init=False)

    def complete(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LlmOutcome:
        self.calls += 1
        if self.delay_ms:
            time.sleep(self.delay_ms / 1000.0)

        rule_proposal = RuleStrategy(self.weights).decide(self.ctx)
        if rule_proposal is None:
            # 이론상 여기 오지 않는다 — 후보가 2개 이상이라 `AgentStrategy`가 LLM을 부른
            # 시점에는 규칙도 최소 한 후보는 점수를 냈어야 한다(표본 설계 전제). 그래도
            # 값을 지어내지 않는다 — 못 고르면 못 고른다고 그대로 알린다.
            reason = "규칙 전략도 고를 후보가 없다."
            text = json.dumps({"chosen_index": 0, "reason": reason}, ensure_ascii=False)
        else:
            chosen_index = rule_proposal.candidate_index
            summary = describe_candidate(self.ctx, chosen_index)
            _, _, quoted = summary.partition(". ")  # "0. 교대 — ..." -> "교대 — ..."
            reason = f"{quoted} 이동을 추천합니다."
            text = json.dumps({"chosen_index": chosen_index, "reason": reason}, ensure_ascii=False)

        return LlmResult(
            text=text,
            input_tokens=None,  # 실제로 세지 않았다 — 0이 아니라 None(`llm.py` 모듈 docstring)
            output_tokens=None,
            latency_ms=self.delay_ms,
            model=FAKE_MODEL_NAME,
        )


def _make_client(
    llm: str, ctx: AgentContext, weights: ScoreWeights, fake_delay_ms: float
) -> LlmClient:
    if llm == "fake":
        return FakeLlmClient(ctx=ctx, weights=weights, delay_ms=fake_delay_ms)
    if llm == "real":
        from app.core.config import Settings  # 지연 import — fake 모드는 필요 없다

        return settings_client(Settings())
    raise ValueError(f"알 수 없는 --llm 값: {llm}")


@dataclass
class _CountingClient:
    """`LlmClient`를 감싸 호출 횟수만 센다. `llm_called` 판정을 fake·real 어느 쪽이든 같은
    방식(실제 `.complete()` 호출 여부)으로 하기 위해서다 — fake는 자체 카운터가 있지만 real
    (`HttpLlmClient`)은 없어, 둘 다 여기서 통일한다."""

    inner: LlmClient
    calls: int = field(default=0, init=False)

    def complete(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LlmOutcome:
        self.calls += 1
        return self.inner.complete(system, user, json_schema=json_schema)


# ── 표본 하나 실행 ──


@dataclass
class SampleResult:
    sample_id: str
    label: str
    description: str
    n_candidates: int
    rule_index: int | None
    rule_score: float | None
    agent_index: int | None
    recommended_by: str | None
    reject_reason: str | None
    match: bool
    reason_text: str | None
    reason_chars: int | None
    reason_sentences: int | None
    input_tokens: int | None
    output_tokens: int | None
    llm_latency_ms: float | None
    rule_latency_ms: float
    agent_latency_ms: float
    llm_called: bool


def run_sample(
    record: dict[str, Any], *, llm: str, fake_delay_ms: float, weights: ScoreWeights
) -> SampleResult:
    ctx = from_json(record["context"])

    rule = RuleStrategy(weights)
    started = time.perf_counter()
    rule_proposal: RerouteProposal | None = rule.decide(ctx)
    rule_latency_ms = (time.perf_counter() - started) * 1000.0

    client = _CountingClient(_make_client(llm, ctx, weights, fake_delay_ms))
    budget = LlmBudget()
    agent = AgentStrategy(client, RuleStrategy(weights), budget=budget)

    started = time.perf_counter()
    agent_proposal: RerouteProposal | None = agent.decide(ctx)
    agent_latency_ms = (time.perf_counter() - started) * 1000.0

    reject_reason = next(iter(agent.rejections), None)  # 표본당 호출 1회라 있어도 하나뿐이다
    reason_text = agent_proposal.reason if agent_proposal is not None else None

    return SampleResult(
        sample_id=record["id"],
        label=record.get("label", ""),
        description=record.get("description", ""),
        n_candidates=record.get("n_candidates", len(ctx.usable_candidates)),
        rule_index=rule_proposal.candidate_index if rule_proposal is not None else None,
        rule_score=rule_proposal.score if rule_proposal is not None else None,
        agent_index=agent_proposal.candidate_index if agent_proposal is not None else None,
        recommended_by=agent_proposal.recommended_by if agent_proposal is not None else None,
        reject_reason=reject_reason.value if reject_reason is not None else None,
        match=(
            (rule_proposal.candidate_index if rule_proposal is not None else None)
            == (agent_proposal.candidate_index if agent_proposal is not None else None)
        ),
        reason_text=reason_text,
        reason_chars=len(reason_text) if reason_text is not None else None,
        reason_sentences=_sentence_count(reason_text) if reason_text is not None else None,
        input_tokens=agent.last_usage.input_tokens if agent.last_usage is not None else None,
        output_tokens=agent.last_usage.output_tokens if agent.last_usage is not None else None,
        llm_latency_ms=agent.last_usage.latency_ms if agent.last_usage is not None else None,
        rule_latency_ms=rule_latency_ms,
        agent_latency_ms=agent_latency_ms,
        llm_called=client.calls > 0,
    )


# ── 통계 ──


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    k = (len(data) - 1) * (pct / 100)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[f] + (data[c] - data[f]) * (k - f)


def _dist_stats(values: list[float]) -> dict[str, Any]:
    """분포 하나(n·평균·p50·p95)를 낸다. 단위는 호출자가 붙인다 — 지연(ms)뿐 아니라
    reason 글자수·문장수처럼 단위 없는 값에도 그대로 쓴다."""
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 2) if values else None,
        "p50": _round_or_none(_percentile(values, 50)),
        "p95": _round_or_none(_percentile(values, 95)),
    }


def _round_or_none(value: float | None, ndigits: int = 2) -> float | None:
    return None if value is None else round(value, ndigits)


def summarize(results: list[SampleResult]) -> dict[str, Any]:
    n = len(results)
    match_count = sum(1 for r in results if r.match)
    llm_accepted = [r for r in results if r.recommended_by == RECOMMENDED_BY_AGENT]
    llm_accepted_match = sum(1 for r in llm_accepted if r.match)

    reject_counts = Counter(r.reject_reason for r in results if r.reject_reason is not None)

    input_tokens = [r.input_tokens for r in results if r.input_tokens is not None]
    output_tokens = [r.output_tokens for r in results if r.output_tokens is not None]

    llm_latencies = [r.llm_latency_ms for r in results if r.llm_latency_ms is not None]
    agent_latencies = [r.agent_latency_ms for r in results]
    rule_latencies = [r.rule_latency_ms for r in results]

    reason_chars = [r.reason_chars for r in results if r.reason_chars is not None]
    reason_sentences = [r.reason_sentences for r in results if r.reason_sentences is not None]

    return {
        "n_samples": n,
        "match_rate": round(match_count / n, 4) if n else None,
        "n_match": match_count,
        "n_llm_accepted": len(llm_accepted),
        "n_llm_accepted_and_match": llm_accepted_match,
        "reject_reason_counts": dict(reject_counts),
        "tokens": {
            "input_sum": sum(input_tokens) if input_tokens else None,
            "input_mean": round(sum(input_tokens) / len(input_tokens), 1) if input_tokens else None,
            "output_sum": sum(output_tokens) if output_tokens else None,
            "output_mean": (
                round(sum(output_tokens) / len(output_tokens), 1) if output_tokens else None
            ),
            "n_with_tokens": len(input_tokens),
            "note": (
                None
                if input_tokens
                else "fake 모드는 토큰을 세지 않는다(None) — real 실행에서만 채워진다"
            ),
        },
        "latency_ms": {
            "llm": _dist_stats(llm_latencies),
            "agent_strategy_total": _dist_stats(agent_latencies),
            "rule_strategy_total": _dist_stats(rule_latencies),
        },
        "reason_chars": _dist_stats([float(x) for x in reason_chars]) if reason_chars else None,
        "reason_sentences": (
            _dist_stats([float(x) for x in reason_sentences]) if reason_sentences else None
        ),
    }


# ── 출력 ──


def to_markdown(results: list[SampleResult], summary: dict[str, Any], *, llm: str) -> str:
    lines = [f"# 재안내 규칙·에이전트 비교 — `--llm {llm}`", ""]

    lines += [
        "## 표본별 결과",
        "",
        "| id | 후보 | rule idx | agent idx | 일치 | recommended_by | 탈락 사유 "
        "| reason 글자수 | reason 문장수 | in tok | out tok | LLM 지연(ms) | 전략 지연(ms) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r.sample_id} | {r.n_candidates} | {_fmt(r.rule_index)} | {_fmt(r.agent_index)} "
            f"| {'O' if r.match else 'X'} | {_fmt(r.recommended_by)} | {_fmt(r.reject_reason)} "
            f"| {_fmt(r.reason_chars)} | {_fmt(r.reason_sentences)} | {_fmt(r.input_tokens)} "
            f"| {_fmt(r.output_tokens)} | {_fmt(r.llm_latency_ms)} | {_fmt(round(r.agent_latency_ms, 2))} |"
        )

    lines += [
        "",
        "## 집계",
        "",
        f"- 표본 수: {summary['n_samples']}",
        f"- 일치율(전체, 가드 탈락·후보 1개 포함): {summary['match_rate']}"
        f"({summary['n_match']}/{summary['n_samples']})",
        f"- LLM이 실제로 채택된 표본: {summary['n_llm_accepted']}건 중 "
        f"{summary['n_llm_accepted_and_match']}건 일치 (모듈 docstring '일치율을 읽을 때 주의' 참고)",
        f"- 가드 탈락 사유 분포: {summary['reject_reason_counts'] or '없음'}",
        (
            f"- 토큰(입력 합/평균, 출력 합/평균): {summary['tokens']['input_sum']}/"
            f"{summary['tokens']['input_mean']}, {summary['tokens']['output_sum']}/"
            f"{summary['tokens']['output_mean']}"
            + (f" — {summary['tokens']['note']}" if summary["tokens"]["note"] else "")
        ),
        (
            f"- LLM 지연 p50/p95(ms, 실제 호출 {summary['latency_ms']['llm']['n']}건): "
            f"{summary['latency_ms']['llm']['p50']}/{summary['latency_ms']['llm']['p95']}"
        ),
        (
            f"- 에이전트 전략 전체 지연 p50/p95(ms): "
            f"{summary['latency_ms']['agent_strategy_total']['p50']}/"
            f"{summary['latency_ms']['agent_strategy_total']['p95']}"
        ),
        (
            f"- 규칙 전략 전체 지연 p50/p95(ms): "
            f"{summary['latency_ms']['rule_strategy_total']['p50']}/"
            f"{summary['latency_ms']['rule_strategy_total']['p95']}"
        ),
        "",
    ]
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def make_figure(results: list[SampleResult], summary: dict[str, Any], *, llm: str, out_path: Path):
    import matplotlib.pyplot as plt

    from DATA_ENGINE.eda import figstyle

    figstyle.apply()
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.5))

    ax = axes[0]
    match_n = summary["n_match"]
    mismatch_n = summary["n_samples"] - match_n
    ax.bar(
        ["일치", "불일치"],
        [match_n, mismatch_n],
        color=[figstyle.COLOR_MODEL, figstyle.COLOR_ACCENT],
    )
    ax.set_title("선택 일치 여부")
    ax.set_ylabel("표본 수")
    for x, y in enumerate([match_n, mismatch_n]):
        ax.text(x, y, str(y), ha="center", va="bottom")

    ax = axes[1]
    rule_mean = summary["latency_ms"]["rule_strategy_total"]["mean"] or 0.0
    agent_mean = summary["latency_ms"]["agent_strategy_total"]["mean"] or 0.0
    ax.bar(
        ["규칙", "에이전트"],
        [rule_mean, agent_mean],
        color=[figstyle.COLOR_BASELINE, figstyle.COLOR_MODEL],
    )
    ax.set_title("전략 전체 지연 평균(ms)")
    ax.set_ylabel("ms")
    for x, y in enumerate([rule_mean, agent_mean]):
        ax.text(x, y, f"{y:.1f}", ha="center", va="bottom")

    fig.suptitle(f"재안내 규칙·에이전트 비교(--llm {llm}, n={summary['n_samples']})")
    figstyle.caption(fig, "AI/validation/TIME/reroute-baseline-check — S15P21A104-331")
    return figstyle.save(fig, out_path.stem, out_dir=out_path.parent, svg=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", choices=["fake", "real"], default="fake")
    parser.add_argument("--samples", type=str, default=str(DEFAULT_SAMPLES))
    parser.add_argument(
        "--out", type=str, default=None, help="출력 JSON 경로(기본: out/compare_<llm>.json)"
    )
    parser.add_argument(
        "--fake-delay-ms", type=float, default=0.0, help="fake 클라이언트 고정 지연(ms)"
    )
    args = parser.parse_args()

    samples_path = Path(args.samples)
    if not samples_path.exists():
        print(
            f"[오류] 표본 파일이 없다: {samples_path} — 먼저 build_samples.py를 실행하라.",
            file=sys.stderr,
        )
        sys.exit(1)
    records = read_samples(samples_path)

    if args.llm == "real":
        print(
            f"[경고] --llm real은 표본 수만큼(이번 실행 {len(records)}회) 실제 LLM 게이트웨이를 "
            "호출한다 — 실행 전 사용자 확인 없이 자동으로 반복 호출하지 않는다"
            "(AI/CLAUDE.md 하드 룰).",
            file=sys.stderr,
        )

    out_path = Path(args.out) if args.out else _HERE.parent / "out" / f"compare_{args.llm}.json"
    figures_dir = _HERE.parent / "figures"

    weights = ScoreWeights()  # 두 전략의 폴백이 같은 가중치를 봐야 "비교"가 된다(모듈 docstring)

    results = [
        run_sample(record, llm=args.llm, fake_delay_ms=args.fake_delay_ms, weights=weights)
        for record in records
    ]
    summary = summarize(results)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "llm": args.llm,
        "samples_path": str(samples_path),
        "fake_delay_ms": args.fake_delay_ms if args.llm == "fake" else None,
        "n_samples": len(records),
        "results": [vars(r) for r in results],
        "summary": summary,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    markdown = to_markdown(results, summary, llm=args.llm)
    md_path.write_text(markdown, encoding="utf-8")

    figure_path = make_figure(
        results, summary, llm=args.llm, out_path=figures_dir / f"compare_{args.llm}"
    )

    print(markdown)
    print(f"[저장] {out_path}")
    print(f"[저장] {md_path}")
    print(f"[저장] {figure_path}")


if __name__ == "__main__":
    main()
