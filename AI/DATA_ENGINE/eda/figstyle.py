"""보고서 그림 공통 스타일 — 한글 폰트, 호선 팔레트, 저장 규약. 136번.

모든 그림은 이 모듈의 `apply()`로 스타일을 맞추고 `save()`로 저장한다. 그림마다 폰트·색·크기를 따로
정하면 슬라이드에 나란히 놓을 때 어긋나서다.

- **폰트**: Windows Malgun Gothic → Noto Sans KR → NanumGothic → AppleGothic 순으로 있는 것을 쓴다.
  하나도 없으면 **경고를 내고** 기본 폰트로 진행한다(라벨이 네모로 깨진 그림을 조용히 내지 않기 위해
  `korean_font_available()`로 호출자가 확인할 수 있다).
- **팔레트**: 서울 지하철 노선 공식 색(1~9호선). 호선이 아닌 범주는 `PALETTE_NEUTRAL`.
- **저장**: `DATA_ENGINE/reports/figures/<name>.png`(300dpi)와 `.svg`를 함께. 반환값은 PNG 경로.
  그림 파일은 gitignore(재생성 가능) — Drive `data/` 미러와 Notion 첨부로 공유한다.
- **인라인 모드**(노트북, 141): `apply(inline=True)`로 켜면 `save()`가 파일을 쓰지 않고 figure를
  그대로 돌려준다(닫지도 않는다). Jupyter가 셀 끝에서 열린 figure를 그리므로 `fig_*(...)` 호출만으로
  인라인 표시가 된다. 백엔드도 건드리지 않는다(inline 백엔드를 Agg로 덮으면 그림이 안 보인다).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

AI_ROOT = Path(__file__).resolve().parents[2]
FIGURES_DIR = AI_ROOT / "DATA_ENGINE" / "reports" / "figures"

KOREAN_FONT_CANDIDATES = ["Malgun Gothic", "Noto Sans KR", "NanumGothic", "AppleGothic"]

# 서울교통공사 노선 색(공식 안내 색상). 그림 안에서 호선을 색으로 구분할 때 항상 이 값을 쓴다.
LINE_COLORS = {
    "1호선": "#0052A4",
    "2호선": "#00A84D",
    "3호선": "#EF7C1C",
    "4호선": "#00A5DE",
    "5호선": "#996CAC",
    "6호선": "#CD7C2F",
    "7호선": "#747F00",
    "8호선": "#E6186C",
    "9호선": "#BDB092",
}
PALETTE_NEUTRAL = ["#1F2937", "#6B7280", "#9CA3AF", "#D1D5DB"]
COLOR_BASELINE = "#6B7280"
COLOR_MODEL = "#0052A4"
COLOR_ACCENT = "#E6186C"
COLOR_REALTIME = "#EF7C1C"  # 실시간 집계가 필요한 세트 표시용

SLIDE_SIZE = (11.0, 6.0)  # inch, 16:9 슬라이드 한 장에 맞는 비율
DPI = 300

_font_name: str | None = None
INLINE = False  # True면 save()가 파일을 쓰지 않고 figure를 돌려준다(노트북용)


def korean_font_available() -> bool:
    return _font_name is not None


def apply(inline: bool = False) -> str | None:
    """rcParams를 통일한다. 적용된 한글 폰트 이름(없으면 None)을 돌려준다.

    `inline=True`는 노트북용 — 파일 저장 대신 figure 반환, 백엔드는 그대로 둔다.
    """
    global _font_name, INLINE
    INLINE = inline
    if not inline:
        matplotlib.use("Agg", force=False)
    installed = {f.name for f in fm.fontManager.ttflist}
    _font_name = next((f for f in KOREAN_FONT_CANDIDATES if f in installed), None)
    if _font_name:
        plt.rcParams["font.family"] = _font_name
    else:
        warnings.warn(
            "한글 폰트가 없어 라벨이 깨질 수 있다: " + ", ".join(KOREAN_FONT_CANDIDATES),
            stacklevel=2,
        )
    plt.rcParams.update(
        {
            "axes.unicode_minus": False,
            "figure.figsize": SLIDE_SIZE,
            "figure.dpi": 110,
            "savefig.dpi": DPI,
            "axes.titlesize": 15,
            "axes.titleweight": "bold",
            "axes.labelsize": 12,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.linestyle": "-",
        }
    )
    return _font_name


def line_color(line: str) -> str:
    return LINE_COLORS.get(str(line), PALETTE_NEUTRAL[1])


def save(fig, name: str, out_dir: Path = FIGURES_DIR, svg: bool = True):
    """`<out_dir>/<name>.png`(+`.svg`) 저장 후 figure를 닫는다. PNG 경로를 돌려준다.

    인라인 모드(`apply(inline=True)`)에서는 저장·닫기 없이 figure 자체를 돌려준다.
    """
    if INLINE:
        return fig
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{name}.png"
    fig.savefig(png, bbox_inches="tight", facecolor="white")
    if svg:
        fig.savefig(out_dir / f"{name}.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png


def caption(fig, text: str) -> None:
    """그림 아래 출처·조건 한 줄(작은 회색 글씨). 슬라이드에 그대로 붙여도 근거가 따라가게."""
    fig.text(0.01, -0.02, text, ha="left", va="top", fontsize=8.5, color=PALETTE_NEUTRAL[1])
