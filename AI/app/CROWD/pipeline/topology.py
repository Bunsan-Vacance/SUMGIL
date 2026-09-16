"""노선 토폴로지(`line_topology.yaml`) 로딩·전개 — 인접역 매핑(`adjacency.py`)의 입력을 만든다.

`DATA_ENGINE/eda/build_congestion_label.py`의 `load_topology`·`expand_stations`·
`resolve_segments`와 같은 동작이다. `app/`은 `DATA_ENGINE/`을 import하지 않는 규약이라
(`AI/CLAUDE.md`) 순수 함수를 여기 두고, 설정 파일은 **경로로만** 참조한다 — YAML은 코드가
아니라 데이터라서다. 기본 경로는 `DATA_ENGINE/conf/line_topology.yaml`이고 배포 시 다른
경로를 넘길 수 있다.

YAML 표기 규칙(`range: [a, b]`, `circular`, `truncated`, 9호선 내림차순 등)은 그 파일의
주석에 있다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

AI_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TOPOLOGY_PATH = AI_ROOT / "DATA_ENGINE" / "conf" / "line_topology.yaml"


def load_topology(path: Path = DEFAULT_TOPOLOGY_PATH) -> list[dict]:
    """YAML의 `segments` 목록을 그대로 돌려준다(역 목록은 아직 펼치지 않은 상태)."""
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f)["segments"]


def expand_stations(spec: list) -> list[int]:
    """`range: [a, b]` 표기를 역번호 목록으로 편다."""
    out: list[int] = []
    for item in spec:
        if isinstance(item, dict) and "range" in item:
            start, end = item["range"]
            out.extend(range(int(start), int(end) + 1))
        else:
            out.append(int(item))
    return out


def resolve_segments(topology: list[dict], available: set[int]) -> tuple[list[dict], pd.DataFrame]:
    """설정의 역 순서를 실제 있는 역만 남겨 확정하고, 빠진 역을 인벤토리로 낸다.

    3호선 충무로·6호선 연신내처럼 물리적으로는 그 호선에 있지만 승하차가 다른 호선에
    계상된 역이 있다. 그 자리에서 양옆 역이 이어지므로 조용히 넘기지 않고 남긴다.
    """
    resolved: list[dict] = []
    gaps: list[dict] = []
    for seg in topology:
        wanted = expand_stations(seg["stations"])
        present = [s for s in wanted if s in available]
        missing = [s for s in wanted if s not in available]
        if missing:
            gaps.append({"line": seg["line"], "segment": seg["segment"], "missing": missing})
        resolved.append({**seg, "stations": present})
    return resolved, pd.DataFrame(gaps, columns=["line", "segment", "missing"])


DEFAULT_CAPACITY_PATH = AI_ROOT / "DATA_ENGINE" / "conf" / "train_capacity.yaml"


def load_capacity(path: Path = DEFAULT_CAPACITY_PATH) -> dict:
    """호선별 편성 량수·1량 정원(`train_capacity.yaml`). 혼잡도(%) 계산의 분모."""
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f)
