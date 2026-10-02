"""systemd 배치 잡 종료 시 node-exporter textfile collector용 `.prom` 파일을 쓴다.

설계 요지
- 최신값 + timestamp만 기록한다(과거 시점 값은 넣지 않음 — 스크레이프 시각에 찍히는 문제 회피).
- 같은 디렉터리의 임시 파일에 쓴 뒤 `os.replace`로 원자적으로 교체한다.
- 디렉터리 미설정·쓰기 실패는 경고만 남기고 exit 0 — 배치 본체를 절대 실패시키지 않는다.
  (job·라벨 이름 위반은 설정 오류라 exit 2로 드러낸다.)

사용 예:
    python -m DATA_ENGINE.observability.export_textfile --job crowd_score_daily \
        --rc 0 --duration 123.4 --step archive=0 --step score=99 --ok-rc 0 --ok-rc 99
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

ENV_DIR = "SUMGIL_TEXTFILE_DIR"
NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
# 라벨 한 쌍: name="escaped value"
_PAIR_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')
SUCCESS_METRIC = "sumgil_job_last_success_timestamp_seconds"
RESERVED_LABELS = ("job", "step")


def escape_label_value(value: str) -> str:
    """라벨 값 escape: 역슬래시, 큰따옴표, 개행."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _unescape_label_value(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt == "n" else nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _format_labels(labels: dict[str, str]) -> str:
    return ",".join(f'{k}="{escape_label_value(v)}"' for k, v in labels.items())


def render(
    job: str,
    rc: int,
    duration: float,
    steps: list[tuple[str, int]],
    ok_rcs: set[int],
    labels: dict[str, str],
    now: int,
    previous_success: int | None,
) -> str:
    """`.prom` 본문을 만든다. 성공 시각은 rc가 ok 집합이면 now, 아니면 이전 값(없으면 생략)."""
    base = {"job": job, **labels}
    lab = _format_labels(base)
    lines: list[str] = []

    def gauge(name: str, help_text: str) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")

    gauge("sumgil_job_last_run_timestamp_seconds", "마지막 실행 종료 시각(epoch 초)")
    lines.append(f"sumgil_job_last_run_timestamp_seconds{{{lab}}} {int(now)}")

    success = now if rc in ok_rcs else previous_success
    if success is not None:
        gauge(SUCCESS_METRIC, "마지막 성공 실행 종료 시각(epoch 초)")
        lines.append(f"{SUCCESS_METRIC}{{{lab}}} {int(success)}")

    gauge("sumgil_job_last_duration_seconds", "마지막 실행 소요 시간(초)")
    lines.append(f"sumgil_job_last_duration_seconds{{{lab}}} {duration:g}")

    gauge("sumgil_job_last_rc", "마지막 실행 종료 코드")
    lines.append(f"sumgil_job_last_rc{{{lab}}} {int(rc)}")

    if steps:
        gauge("sumgil_job_step_last_rc", "마지막 실행의 단계별 종료 코드")
        for name, step_rc in steps:
            step_lab = _format_labels({**base, "step": name})
            lines.append(f"sumgil_job_step_last_rc{{{step_lab}}} {int(step_rc)}")

    return "\n".join(lines) + "\n"


def read_previous_success(path: Path, labels: dict[str, str]) -> int | None:
    """기존 파일에서 같은 라벨 집합의 마지막 성공 시각을 읽는다. 없거나 파싱 불가면 None."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        if not line.startswith(SUCCESS_METRIC + "{"):
            continue
        try:
            head, _, value = line.rpartition("}")
            body = head[len(SUCCESS_METRIC) + 1 :]
            found = {k: _unescape_label_value(v) for k, v in _PAIR_RE.findall(body)}
            if found == labels:
                return int(float(value.strip()))
        except ValueError:
            continue
    return None


def write_atomic(path: Path, text: str) -> None:
    """같은 디렉터리의 `.<이름>.tmp`에 쓰고 os.replace로 교체한다."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _step(value: str) -> tuple[str, int]:
    name, sep, rc = value.rpartition("=")
    if not sep or not name:
        raise argparse.ArgumentTypeError(f"--step은 name=rc 형식이어야 한다: {value!r}")
    try:
        return name, int(rc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--step rc가 정수가 아니다: {value!r}") from exc


def _label(value: str) -> tuple[str, str]:
    key, sep, val = value.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"--label은 k=v 형식이어야 한다: {value!r}")
    return key, val


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="배치 잡 관측 지표 textfile 생산자")
    p.add_argument("--job", required=True)
    p.add_argument("--rc", type=int, required=True)
    p.add_argument("--duration", type=float, required=True)
    p.add_argument("--step", action="append", type=_step, default=[], help="name=rc (반복)")
    p.add_argument(
        "--ok-rc", action="append", type=int, default=None, help="성공으로 볼 rc (반복, 기본 0)"
    )
    p.add_argument("--dir", default=None, help=f"출력 디렉터리(기본: 환경변수 {ENV_DIR})")
    p.add_argument("--label", action="append", type=_label, default=[], help="추가 라벨 k=v (반복)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)  # 형식 오류는 argparse가 exit 2

    if not NAME_RE.match(args.job):
        print(f"[observability] 잘못된 job 이름: {args.job!r}", file=sys.stderr)
        return 2
    labels: dict[str, str] = {}
    for key, val in args.label:
        if not NAME_RE.match(key) or key in RESERVED_LABELS:
            print(f"[observability] 잘못된 라벨 이름: {key!r}", file=sys.stderr)
            return 2
        labels[key] = val

    out_dir = args.dir or os.environ.get(ENV_DIR)
    if not out_dir:
        print("textfile dir 미설정 - 건너뜀")
        return 0

    ok_rcs = set(args.ok_rc) if args.ok_rc else {0}
    path = Path(out_dir) / f"sumgil_{args.job}.prom"
    try:
        previous = read_previous_success(path, {"job": args.job, **labels})
        text = render(
            args.job, args.rc, args.duration, args.step, ok_rcs, labels, int(time.time()), previous
        )
        write_atomic(path, text)
    except OSError as exc:
        print(f"[observability] 경고: textfile 쓰기 실패({path}): {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
