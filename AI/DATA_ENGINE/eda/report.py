"""reports/bike_weather_eda.md 생성.

전제: data/BYC/raw/realtime 스냅샷, station_5min 파싱 결과(data/BYC/interim), ASOS 백필
(data/EXTERNAL/raw/weather/asos)이 있어야 한다. 날씨 영향(3번 섹션)은 station_5min × ASOS로,
재고 분포·공간구조(1·2·4번)는 실시간 스냅샷 누적량만큼만 반영된다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.report
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from DATA_ENGINE.eda import analysis

# 한글 폰트가 없으면 그래프 제목이 네모로 깨진다 — 있는 것만 골라서 적용, 없으면 기본값 유지.
_KOREAN_FONT_CANDIDATES = ["AppleGothic", "Noto Sans KR", "NanumGothic", "Malgun Gothic"]
_installed = {f.name for f in fm.fontManager.ttflist}
_font = next((f for f in _KOREAN_FONT_CANDIDATES if f in _installed), None)
if _font:
    plt.rcParams["font.family"] = _font
plt.rcParams["axes.unicode_minus"] = False

AI_ROOT = Path(__file__).resolve().parents[2]
BIKE_RAW = AI_ROOT / "data" / "BYC" / "raw"
WEATHER_RAW = AI_ROOT / "data" / "EXTERNAL" / "raw" / "weather"
DATA_INTERIM = AI_ROOT / "data" / "BYC" / "interim"
REPORTS_DIR = AI_ROOT / "DATA_ENGINE" / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"


def _load_snapshots() -> pd.DataFrame:
    files = sorted((BIKE_RAW / "realtime").glob("dt=*/hh=*/snapshot_*.parquet"))
    if not files:
        raise FileNotFoundError(
            "data/BYC/raw/realtime 에 스냅샷이 없습니다. "
            "scripts/start_bike_poller.sh 로 폴러를 먼저 돌려서 데이터를 쌓으세요."
        )
    return pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)


def _load_rental_hourly() -> pd.DataFrame:
    """station_5min(5분단위 O-D)을 시간 단위로 집계. rental_history(월별 집계)는 시간
    해상도가 없어 날씨 상관분석엔 못 쓴다 — 정류소/자치구 월간 총량 파악용으로만 별도 사용."""
    files = sorted(DATA_INTERIM.glob("station_5min_*.parquet"))
    if not files:
        raise FileNotFoundError(
            "data/BYC/interim 에 station_5min 파싱 결과가 없습니다. "
            "DATA_ENGINE/reports/download_guide.md 안내대로 원본을 받아 DATA_ENGINE/eda/parsers.py로 파싱하세요."
        )
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df = df[df["agg_basis"] == "출발시간"]  # 대여(수요) 기준 — 도착시간까지 합치면 중복 집계됨
    df["dt_hour"] = pd.to_datetime(df["dt_5min"]).dt.floor("h")
    # 일부 원본 zip에 0-row 빈 CSV가 섞여 있으면 concat 시 trip_count가 object dtype으로
    # 깨진다 — 합산 전에 명시적으로 숫자로 캐스팅.
    df["trip_count"] = pd.to_numeric(df["trip_count"], errors="coerce")
    return df.groupby("dt_hour")["trip_count"].sum().reset_index(name="rent_count")


def _load_weather_hourly() -> pd.DataFrame:
    """ASOS 백필(과거)을 시간당 기온·강수량으로 정규화. 초단기실황/예보(진행형, 데이터量 적음)는
    아직 안 합침 — 별도로 쌓이는 대로 나중에 추가."""
    files = sorted((WEATHER_RAW / "asos").glob("*.parquet"))
    if not files:
        raise FileNotFoundError(
            "data/EXTERNAL/raw/weather/asos 에 데이터가 없습니다. 백필을 먼저 실행하세요."
        )
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    weather = df.rename(columns={"tm": "dt_hour", "ta": "temp_c"})[
        ["dt_hour", "temp_c", "rn"]
    ].copy()
    # RN -9.0은 미관측/무강수 구분 코드 — 여기서는 강수 유무 비교가 목적이라 0으로 취급.
    weather["precip_mm"] = weather["rn"].where(weather["rn"] > 0, 0.0)
    return weather.drop(columns="rn")


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
