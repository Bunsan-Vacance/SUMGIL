"""reports/bike_weather_eda.md 생성 — 데이터가 모인 뒤에 실행한다.

전제: data/raw/bike/realtime 스냅샷이 충분히 쌓이고, rental_history/weather 파서로
data/interim 산출물이 만들어진 이후. 지금은 데이터가 없어 실행하지 않는다.

실행:
    cd AI
    python -m src.eda.report
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from src.eda import analysis

AI_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = AI_ROOT / "data" / "raw"
DATA_INTERIM = AI_ROOT / "data" / "interim"
REPORTS_DIR = AI_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"


def _load_snapshots() -> pd.DataFrame:
    files = sorted((DATA_RAW / "bike" / "realtime").glob("dt=*/hh=*/snapshot_*.parquet"))
    if not files:
        raise FileNotFoundError(
            "data/raw/bike/realtime 에 스냅샷이 없습니다. "
            "scripts/start_bike_poller.sh 로 폴러를 먼저 돌려서 데이터를 쌓으세요."
        )
    return pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)


def _load_rental_hourly() -> pd.DataFrame:
    files = sorted(DATA_INTERIM.glob("rental_history_*.parquet"))
    if not files:
        raise FileNotFoundError(
            "data/interim 에 rental_history 파싱 결과가 없습니다. "
            "reports/download_guide.md 안내대로 원본을 받아 src/eda/parsers.py로 파싱하세요."
        )
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df["dt_hour"] = pd.to_datetime(df["rent_dt"]).dt.floor("h")
    return df.groupby("dt_hour").size().reset_index(name="rent_count")


def _load_weather_hourly() -> pd.DataFrame:
    files = sorted((DATA_RAW / "weather").rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(
            "data/raw/weather 에 데이터가 없습니다. 백필/폴러를 먼저 실행하세요."
        )
    # 실제 컬럼 정규화(ASOS 텍스트 파싱 헤더 확정, 초단기실황 category→wide 변환)는
    # 데이터 확보 후 실제 응답 스키마를 보고 맞춘다. 지금은 자리만 잡아둔다.
    raise NotImplementedError("weather_hourly 정규화는 실제 ASOS/초단기 응답 스키마 확인 후 구현")


def generate() -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = _load_snapshots()
    rental_hourly = _load_rental_hourly()
    weather_hourly = _load_weather_hourly()

    inv = analysis.inventory_distribution(snapshots)
    heatmap = analysis.weekday_hour_heatmap(snapshots)
    impact = analysis.weather_impact(rental_hourly, weather_hourly)
    spatial = analysis.spatial_neighbor_correlation(snapshots)

    fig, ax = plt.subplots(figsize=(10, 4))
    sns.heatmap(heatmap, ax=ax, cmap="viridis")
    ax.set_title("요일×시간대 재고 히트맵")
    fig.savefig(FIGURES_DIR / "weekday_hour_heatmap.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    lines = [
        "# 따릉이 재고 × 날씨 EDA\n",
        "## 1. 재고 분포\n",
        f"```\n{inv['count_desc']}\n```\n",
        "**모델링 시사점**\n- TODO\n- TODO\n- TODO\n",
        "## 2. 시간 패턴\n",
        "![요일×시간대 히트맵](figures/weekday_hour_heatmap.png)\n",
        "**모델링 시사점**\n- TODO\n- TODO\n- TODO\n",
        "## 3. 날씨 영향\n",
        f"강수 구간별 대여건수:\n```\n{impact.precip_bin_summary}\n```\n",
        f"Kruskal-Wallis p-value: {impact.precip_kruskal_pvalue:.4g}\n",
        f"원계열 상관: {impact.raw_corr:.3f}, 잔차(요일·시간대 제거) 상관: {impact.residual_corr:.3f}\n",
        "**모델링 시사점**\n- TODO\n- TODO\n- TODO\n",
        "## 4. 공간 구조\n",
        f"반경별 이웃 재고 상관: {spatial}\n",
        "**모델링 시사점**\n- TODO\n- TODO\n- TODO\n",
    ]

    out_path = REPORTS_DIR / "bike_weather_eda.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    path = generate()
    print(f"리포트 생성 완료: {path}")
