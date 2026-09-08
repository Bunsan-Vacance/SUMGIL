"""reports/crowd_eda.md 생성 — CROWD 혼잡도 스냅샷 1단계(정적 프로파일) EDA.

전제: data/CROWD/raw/ 에 서울교통공사 CSV(1~8호선) + 9호선 xlsx 6개(2020~2025)가 있어야
한다. 두 원천 모두 날짜 컬럼이 없는 "대표 1주 스냅샷"이라 일 단위 시계열 상관분석에는 쓸 수
없다 — 자세한 배경은 이 리포트 1절과 AI/validation/CROWD/README.md 참고.

실행:
    cd AI
    python -m DATA_ENGINE.eda.report_crowd
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from DATA_ENGINE.eda import analysis_crowd, parsers_crowd

# 한글 폰트가 없으면 그래프 제목이 네모로 깨진다 — 있는 것만 골라서 적용, 없으면 기본값 유지.
_KOREAN_FONT_CANDIDATES = ["AppleGothic", "Noto Sans KR", "NanumGothic", "Malgun Gothic"]
_installed = {f.name for f in fm.fontManager.ttflist}
_font = next((f for f in _KOREAN_FONT_CANDIDATES if f in _installed), None)
if _font:
    plt.rcParams["font.family"] = _font
plt.rcParams["axes.unicode_minus"] = False

AI_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = AI_ROOT / "DATA_ENGINE" / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

_HIGH_THRESHOLD = 150.0


def generate() -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    long_df = parsers_crowd.build_congestion_long()
    parsers_crowd.save_interim(long_df)

    coverage = analysis_crowd.day_type_direction_coverage(long_df)
    pivot, cell_counts = analysis_crowd.station_time_pivot(long_df)
    missing = analysis_crowd.missing_cell_inventory(pivot)
    outliers = analysis_crowd.outlier_flags(long_df, high_threshold=_HIGH_THRESHOLD)

    line9_df = long_df[long_df["source"] == "line9"]
    yoy = analysis_crowd.year_over_year_snapshot_reference(line9_df)

    # 9호선 상선·일반·평일, 가장 최근 연도의 역×시간대 히트맵 1장.
    latest_year = int(line9_df["year"].max())
    sample = line9_df[
        (line9_df["direction"] == "상선")
        & (line9_df["train_type"] == "일반")
        & (line9_df["day_type"] == "평일")
        & (line9_df["year"] == latest_year)
    ]
    heatmap_data = sample.pivot_table(
        index="station_name", columns="time_slot", values="congestion_pct", aggfunc="mean"
    )
    fig, ax = plt.subplots(figsize=(14, 8))
    sns.heatmap(heatmap_data, ax=ax, cmap="viridis")
    ax.set_title(f"9호선 상선·일반·평일 역×시간대 혼잡도 ({latest_year}년)")
    fig.savefig(FIGURES_DIR / "crowd_line9_weekday_heatmap.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    dup_cells = int((cell_counts.fillna(0) > 1).sum().sum())
    duplicate_note = (
        f"중복 관측 셀 {dup_cells}개 발견 — 평균으로 합쳐졌으니 원본 확인이 필요하다."
        if dup_cells
        else "중복 관측 셀 없음."
    )
    missing_block = (
        f"```\n{missing.head(20).to_string(index=False)}\n```\n" if len(missing) else "결측 셀 없음.\n"
    )
    outlier_block = (
        f"```\n{outliers['flag_reason'].value_counts().to_string()}\n```\n"
        if len(outliers)
        else "이상치 없음.\n"
    )

    lines = [
        "# 지하철 혼잡도 스냅샷 EDA (1단계: 정적 프로파일)\n",
        "## 1. 개요\n",
        (
            "데이터 출처: 서울교통공사 지하철혼잡도정보 CSV(1~8호선) + 9호선 역별 시간별 "
            f"혼잡도 xlsx 6개년({sorted(int(y) for y in line9_df['year'].unique())}). "
            f"총 {len(long_df):,}행.\n"
        ),
        (
            '**두 원천 모두 날짜 컬럼이 없는 "대표 1주 평균" 스냅샷이다** — 요일별 시계열이 '
            "아니라 역×시간대×요일유형 단위의 정적 프로파일로만 다뤄야 한다.\n"
        ),
        "**모델링 시사점**\n- TODO\n",
        "## 2. 커버리지 비대칭\n",
        "요일 구분:\n",
        f"```\n{coverage['day_type'].to_string()}\n```\n",
        "상하/내외선 구분:\n",
        f"```\n{coverage['direction'].to_string()}\n```\n",
        (
            "서울시 CSV(요일구분: 평일/토요일/일요일, 방향: 상선/하선 또는 2호선만 내선/외선)와 "
            "9호선 xlsx(요일구분: 평일/휴일, 방향: 상선/하선만)의 체계가 다르다 — 하나로 "
            "합치거나 재라벨링하지 않았다.\n"
        ),
        "**모델링 시사점**\n- TODO\n",
        "## 3. 결측 인벤토리\n",
        f"결측 셀 {len(missing):,}개.\n",
        missing_block,
        "표본이 부족한 셀은 채우지 않았다.\n",
        "**모델링 시사점**\n- TODO\n",
        "## 4. 이상치 플래그\n",
        f"플래그된 행 {len(outliers):,}개 (0% 이하, 100% 초과, {_HIGH_THRESHOLD:g}% 초과 기준).\n",
        outlier_block,
        duplicate_note + "\n",
        "**모델링 시사점**\n- TODO\n",
        "## 5. 역×시간대×요일유형 프로파일\n",
        "![9호선 상선·일반·평일 히트맵](figures/crowd_line9_weekday_heatmap.png)\n",
        "**모델링 시사점**\n- TODO\n",
        "## 6. 연도별 스냅샷 비교 (추세 참고용)\n",
        f"```\n{yoy.head(20).to_string()}\n```\n",
        (
            "연 1회 대표주간 관측치이므로 통계적 유의성 주장 대상이 아니며, 일 단위 상관분석에 "
            "쓸 수 없다. 절대값 차이가 아니라 변화율(pct_change)로만 표기했다.\n"
        ),
        "**모델링 시사점**\n- TODO\n",
        "## 7. 모델링 시사점 / 다음 단계\n",
        (
            "혼잡도%는 스냅샷이라 일 단위 상관분석 대상이 될 수 없다. 실제 동적 신호가 "
            "필요하면 `CardSubwayTime`(호선별 역별 시간대별 승하차, OA-12252) 확보가 다음 "
            "단계다 — 단 호출 범위(기간·건수)를 사용자와 먼저 맞춰야 한다(`AI/CLAUDE.md` "
            "하드 룰). 이번 리포트 범위에는 포함하지 않는다.\n"
        ),
    ]

    out_path = REPORTS_DIR / "crowd_eda.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    path = generate()
    print(f"리포트 생성 완료: {path}")
