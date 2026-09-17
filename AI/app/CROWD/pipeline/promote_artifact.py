"""아티팩트 승격 CLI — `_experiments/`의 학습 산출물을 `models/CROWD/`로 복사한다(200 B부).

어제(145 후속)까지의 승격 절차는 손으로 했다: 실험 폴더에서 학습 → 비교 → 폴더를 **복사**해
`models/CROWD/<이름>/`에 두고 → `app/core/config.py`의 `crowd_lgbm_artifact`/`crowd_dl_artifact`를
그 폴더명으로 고정 → 서빙 표 재생성 → `SERVING_CONTRACT.md` 예시 갱신 → BE 통지. 이 스크립트는
그 절차의 **복사 + 검증 + 체크리스트 출력**만 자동화한다 — 설정값 고정은 사람이 직접 한다(운영
기본값을 스크립트가 조용히 바꾸지 않기 위해서).

## 검증

`src`는 `meta.json`이 있는 디렉터리여야 한다. `model_kind`(`predictor.artifact_kind`, 키가 없으면
`lightgbm`)에 따라 필요한 파일이 다르다:

- `lightgbm`: `lookup.parquet` + `meta.json["model_files"]`에 적힌 모든 부스터 파일
  (`train.py:save_artifact` 참고).
- `dl`: `dl/infer.py:DLResidualPredictor`가 여는 네 파일 — `model.pt`(state_dict)·`scale.parquet`·
  `event_stats.parquet`·`lookup.parquet`(`dl/train_dl.py:save_artifact` 참고). 하나라도 없으면
  배치가 그 아티팩트를 로드하는 순간 죽으므로 승격 전에 막는다.

## 대상 보호

대상 폴더가 이미 있으면 `--force` 없이는 거부한다. `--force`를 줘도 대상 이름이 **현재 배포 중인
아티팩트**(`get_settings().crowd_lgbm_artifact`/`crowd_dl_artifact`)와 같으면 거부한다 — 운영 중인
폴더를 승격 스크립트가 지우는 사고를 막기 위해서다. 옛 아티팩트는 지우지 않는다(롤백은 설정값을
되돌리는 것뿐).

## 사람이 해야 하는 것

이 스크립트는 `app/core/config.py`를 편집하지 않는다 — 바꿀 줄을 출력만 한다. 그 다음은
`MODEL_REGISTRY.md`(3절 아티팩트 표, "4b. 아티팩트 승격 절차")의 체크리스트를 따른다.

실행:
    cd AI
    python -m app.CROWD.pipeline.promote_artifact --src models/CROWD/_experiments/ops/<이름>
    python -m app.CROWD.pipeline.promote_artifact --src <경로> --name <폴더명> --dst-root <루트>
    python -m app.CROWD.pipeline.promote_artifact --src <경로> --force   # 대상 폴더가 있어도 교체
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from app.CROWD.pipeline.predictor import artifact_kind, latest_artifact

# `dl/infer.py:DLResidualPredictor.__init__`가 여는 파일 — 여기와 어긋나면 배치가 로드 시점에 죽는다.
DL_REQUIRED_FILES = ("model.pt", "scale.parquet", "event_stats.parquet", "lookup.parquet")

CHECKLIST = """[체크리스트] 아래는 사람이 직접 확인한다(순서대로).
 1. 설정값 고정 — 위에 출력된 줄을 app/core/config.py에 반영한다.
 2. pytest -q test/CROWD/ 를 통과시킨다.
 3. batch_predict --date <최근 2일> 로 서빙 표를 재생성한다.
 4. SERVING_CONTRACT.md 1·3·4절 예시 값을 갱신한다(테스트는 값을 보지 않는다).
 5. MODEL_REGISTRY.md 3절 아티팩트 표를 갱신한다.
 6. BE 통지문을 .claude/handoff/TO_BE-crowd-....md 로 남긴다."""


def _config_key(kind: str) -> str:
    return "crowd_lgbm_artifact" if kind == "lightgbm" else "crowd_dl_artifact"


def _pinned_name(kind: str, settings: Any) -> str | None:
    return getattr(settings, _config_key(kind))


def _model_files_flat(meta: dict) -> list[str]:
    """`meta["model_files"]`(`{target: {group_key: 파일명}}`)를 파일명 목록으로 편다."""
    out: list[str] = []
    for by_group in (meta.get("model_files") or {}).values():
        out.extend(by_group.values())
    return out


# ── 검증 ──
def validate_artifact(src: Path) -> tuple[str, dict]:
    """`src`가 승격 가능한 아티팩트인지 확인하고 `(kind, meta)`를 돌려준다. 문제가 있으면 `SystemExit`."""
    src = Path(src)
    if not src.is_dir():
        raise SystemExit(f"[승격] src가 디렉터리가 아니다: {src}")
    meta_path = src / "meta.json"
    if not meta_path.exists():
        raise SystemExit(f"[승격] meta.json이 없다: {meta_path}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[승격] meta.json 파싱 실패({meta_path}): {exc}") from exc

    kind = artifact_kind(src)
    missing: list[str] = []
    if kind == "lightgbm":
        if not (src / "lookup.parquet").exists():
            missing.append("lookup.parquet")
        if not meta.get("model_files"):
            missing.append("meta.json:model_files")
        for name in _model_files_flat(meta):
            if not (src / name).exists():
                missing.append(name)
    elif kind == "dl":
        for name in DL_REQUIRED_FILES:
            if not (src / name).exists():
                missing.append(name)
    else:
        raise SystemExit(f"[승격] 알 수 없는 model_kind({kind!r}) — {src}")
    if missing:
        raise SystemExit(f"[승격] 파일 누락({src}): {', '.join(missing)}")
    return kind, meta


def format_summary(src: Path, kind: str, meta: dict) -> str:
    """한 화면 요약 — 무엇을 승격하는지 사람이 옮기기 전에 확인하는 표."""
    lines = [f"[요약] {src.name}", f"  kind: {kind}"]
    if kind == "lightgbm":
        lines.append(f"  feature_set: {meta.get('feature_set')}")
        lines.append(f"  구간: {meta.get('train_start')} ~ {meta.get('train_end')}")
        lines.append(f"  n_train_rows: {meta.get('n_train_rows')}")
        masking = (meta.get("training") or {}).get("masking") or {}
        if masking:
            lines.append(f"  masking: {masking.get('mode')}")
    else:  # dl
        lines.append(f"  model: {meta.get('model')}")
        lines.append(f"  splits: {meta.get('splits')}")
        lines.append(f"  n_train_samples: {meta.get('n_train_samples')}")
    lines.append(f"  created_at: {meta.get('created_at')}")
    return "\n".join(lines)


# ── 복사 ──
def copy_artifact(
    src: Path, dst_root: Path, name: str, kind: str, settings: Any, force: bool
) -> Path:
    """`src` → `dst_root/name`. 대상이 있으면 `force` 없이 거부하고, `force`여도 고정 아티팩트는 거부한다."""
    dst_root = Path(dst_root)
    dst = dst_root / name
    if dst.exists():
        if not force:
            raise SystemExit(f"[승격] 대상이 이미 있다({dst}) — 덮어쓰려면 --force")
        pinned = _pinned_name(kind, settings)
        if pinned is not None and name == pinned:
            raise SystemExit(
                f"[승격] {name!r}은(는) 현재 배포 중인 아티팩트다"
                f"(settings.{_config_key(kind)}) — --force로도 덮어쓰지 않는다"
            )
        shutil.rmtree(dst)
    dst_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    return dst


# ── 실행 ──
def run(args: argparse.Namespace, settings: Any | None = None) -> Path:
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()

    src = Path(args.src)
    kind, meta = validate_artifact(src)
    print(format_summary(src, kind, meta))

    dst_root = (
        Path(args.dst_root) if getattr(args, "dst_root", None) else Path(settings.crowd_models_dir)
    )
    name = args.name or src.name
    dst = copy_artifact(src, dst_root, name, kind, settings, bool(args.force))
    print(f"[복사] {src} -> {dst}")

    line = (
        f'crowd_lgbm_artifact: str | None = "{name}"'
        if kind == "lightgbm"
        else f'crowd_dl_artifact: str = "{name}"'
    )
    print(f"[설정] app/core/config.py에서 바꿀 줄:\n  {line}")
    print(CHECKLIST)

    latest = latest_artifact(dst_root, kind=kind)
    print(f"[참고] latest_artifact(kind={kind!r}) = {latest} (이름 정렬 최신 — 정보용)")
    return dst


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--src", required=True, help="models/CROWD/_experiments/... 아래 아티팩트 폴더")
    ap.add_argument(
        "--dst-root", default=None, help="기본 settings.crowd_models_dir(보통 models/CROWD)"
    )
    ap.add_argument("--name", default=None, help="대상 폴더명(기본값: src의 폴더명)")
    ap.add_argument(
        "--force", action="store_true", help="대상 폴더가 있어도 덮어쓴다(고정 아티팩트는 예외)"
    )
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
