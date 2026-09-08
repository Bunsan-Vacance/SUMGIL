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

    # 역×시간대 패턴 형태 기반 군집화 (Notion "관련 논문" [장려상] 지하철 혼잡도 상관분석의
    # Correlation similarity 기반 K-means를 근사) — 위 heatmap_data(9호선 상선·일반·평일,
    # 최신 연도)를 그대로 재사용한다.
    n_clusters = 3
    cluster_labels = analysis_crowd.cluster_station_profiles(heatmap_data, n_clusters=n_clusters)
    cluster_profiles = heatmap_data.loc[cluster_labels.index].groupby(cluster_labels).mean()

    fig, ax = plt.subplots(figsize=(12, 5))
    for cluster_id, profile in cluster_profiles.iterrows():
        ax.plot(profile.index, profile.to_numpy(), marker="o", label=f"군집 {cluster_id}")
    ax.set_title(f"9호선 상선·일반·평일 군집별 평균 혼잡도 패턴 ({latest_year}년)")
    ax.set_xlabel("시간대")
    ax.set_ylabel("혼잡도(%)")
    ax.tick_params(axis="x", rotation=90)
    ax.legend()
    fig.savefig(FIGURES_DIR / "crowd_line9_station_clusters.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    cluster_members = (
        cluster_labels.rename("cluster")
        .reset_index()
        .sort_values(["cluster", "station_name"])
        .groupby("cluster")["station_name"]
        .apply(lambda s: ", ".join(s))
    )

    dup_cells = int((cell_counts.fillna(0) > 1).sum().sum())
    duplicate_note = (
        f"중복 관측 셀 {dup_cells}개 발견 — 평균으로 합쳐졌으니 원본 확인이 필요하다."
        if dup_cells
        else "중복 관측 셀 없음."
    )
    missing_block = (
        f"```\n{missing.head(20).to_string(index=False)}\n```\n"
        if len(missing)
        else "결측 셀 없음.\n"
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
        (
            "**모델링 시사점**\n"
            "- 이 데이터만으로는 일 단위 상관·회귀 학습이 불가능하다 — 정적 프로파일은 "
            "타겟 라벨의 기준값(등급 경계·평균 패턴)이나 동적 신호(승하차 인원 등)의 보정 "
            "기준으로만 쓴다.\n"
        ),
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
        (
            "**모델링 시사점**\n"
            "- day_type은 학습용으로 평일/주말(토요일+일요일)/휴일 3범주로 통합 파생하되, "
            "원본 값(9호선의 토요일 구분 불가 등)은 별도 컬럼으로 남겨 손실을 감춘 것처럼 "
            "취급하지 않는다.\n"
            "- 여러 논문(장려상 상관분석, 기상 요소 예측모델)에서 전역 단일 모델보다 역별/"
            "군집별 모델이 우세했다 — direction·line 조합별로 나뉜 이 비대칭 구조는 애초에 "
            "군집·역 단위 모델링과 궁합이 맞는 형태로 본다(5절 군집화 참고).\n"
        ),
        "## 3. 결측 인벤토리\n",
        f"결측 셀 {len(missing):,}개.\n",
        missing_block,
        "표본이 부족한 셀은 채우지 않았다.\n",
        (
            "**모델링 시사점**\n"
            "- 결측은 대부분 심야(00:00~00:30대) 셀에 몰려 있다 — 미보간 상태를 유지하고, "
            "학습 시에는 해당 셀을 라벨에서 제외하거나 결측 여부 자체를 피처(운행 유무)로 "
            "쓴다. 참고 논문의 KDTree 최근접 역 보간 방식은 표본 부족 구간에 값을 채우지 "
            "않는다는 우리 원칙과 충돌해 채택하지 않는다.\n"
        ),
        "## 4. 이상치 플래그\n",
        f"플래그된 행 {len(outliers):,}개 (0% 이하, 100% 초과, {_HIGH_THRESHOLD:g}% 초과 기준).\n",
        outlier_block,
        duplicate_note + "\n",
        (
            "**모델링 시사점**\n"
            "- `zero`(0% 이하) 플래그는 대부분 막차 이후~첫차 이전 미운행 시간대로 추정된다 — "
            "이상치로 제거하지 않고 '무혼잡'이라는 정상 신호로 학습에 남긴다.\n"
            "- `over_100`/`very_high`는 정의상 존재 가능한 값이다(정원 초과). 국토부 고시 "
            "제2023-414호가 열차 혼잡도 150/170/190%, 역사 혼잡도 130/150/170%를 법정 "
            "임계치로 이미 정의해뒀으므로, 삭제 대상이 아니라 우리 서비스의 혼잡도 등급"
            "(보통/주의/혼잡/심각) 라벨링 기준으로 그대로 채택한다.\n"
        ),
        "## 5. 역×시간대×요일유형 프로파일\n",
        "![9호선 상선·일반·평일 히트맵](figures/crowd_line9_weekday_heatmap.png)\n",
        "### 5.1 시간대 패턴 기반 역 군집화\n",
        (
            f"위 히트맵과 같은 슬라이스(9호선 상선·일반·평일, {latest_year}년)에 행 단위 "
            "z-score 표준화 후 K-means(k=3)를 적용해 절대 혼잡도 수준이 아니라 '언제 피크가 "
            "오는가'라는 패턴 모양으로 역을 묶었다 — [장려상] 지하철 혼잡도 상관분석 논문의 "
            "Correlation similarity 기반 K-means 클러스터링을 근사한 것이다.\n"
        ),
        "![9호선 군집별 평균 혼잡도 패턴](figures/crowd_line9_station_clusters.png)\n",
        "군집별 소속 역:\n",
        f"```\n{cluster_members.to_string()}\n```\n",
        (
            "**모델링 시사점**\n"
            "- 군집 결과가 논문처럼 뚜렷한 형태별 그룹(예: 오전 출근 집중형/오후 피크형/쌍봉형)"
            "으로 나뉘는지 위 소속 역 목록으로 확인한다. 그렇다면 전역 단일 모델 대신 "
            "군집별 모델(XGBoost/LightGBM 등 트리 기반) 학습이 논문 결론과 일치한다.\n"
            "- 이 군집 라벨(cluster_id) 자체를 역 단위 범주형 피처로 학습에 투입할 수 있다 — "
            "새 역이 추가돼도 같은 파이프라인(표준화+예측)으로 군집을 배정하면 재사용 가능.\n"
        ),
        "## 6. 연도별 스냅샷 비교 (추세 참고용)\n",
        f"```\n{yoy.head(20).to_string()}\n```\n",
        (
            "연 1회 대표주간 관측치이므로 통계적 유의성 주장 대상이 아니며, 일 단위 상관분석에 "
            "쓸 수 없다. 절대값 차이가 아니라 변화율(pct_change)로만 표기했다.\n"
        ),
        (
            "**모델링 시사점**\n"
            "- '기상 요소와 주기성 및 특이성을 고려한 지하철 혼잡도 예측 모델' 논문은 학습 "
            "기간을 2021~2023년에서 2023년 단일 연도로 좁히자 RMSE가 10.743→4.265(약 60%↓)"
            "로 개선됐다고 보고한다(코로나 전후 이용 패턴 변화 때문) — 우리도 CardSubwayTime "
            "확보 후 학습 윈도우를 무조건 늘리기보다 예측 시점에 가까운 최신 1개년 우선 + "
            "이벤트 변수(공휴일·경기 등) 추가 전략을 기본값으로 검증한다.\n"
            "- 이 원칙은 이 스냅샷 데이터(연 1회 관측) 자체로는 직접 검증할 수 없다 — "
            "일 단위 동적 데이터 확보 후 별도 실험이 필요하다.\n"
        ),
        "## 7. 종합 모델링 시사점\n",
        (
            "혼잡도%는 스냅샷이라 그 자체로는 일 단위 상관분석·회귀 학습 대상이 될 수 없다. "
            "하지만 (a) 서비스가 채택할 혼잡도 등급 정의(4절 국토부 고시 임계치), (b) 역 "
            "군집 구조(5.1절), (c) 최신성 우선 학습 전략(6절)이라는 세 가지 재사용 가능한 "
            "산출물을 이번 스냅샷만으로 확보했다. 다음 단계는 8·9절의 데이터 요구사항을 "
            "채워 실제 동적 학습 데이터셋을 구성하는 것이다.\n"
        ),
        "## 8. 논문 기반 데이터 요구사항 점검\n",
        (
            "Notion `특화 PJT / 실험실 / [CROWD] 혼잡도 / 관련 논문` 정리(취소선 처리된 "
            "'설명가능한 인공지능...' XAI 논문과 '지하철역 혼잡도 실시간 예측 모델 나왔다' "
            "행안부 사례 2건은 서비스 관련성이 낮아 제외)를 근거로, 예측 모델에 필요한 "
            "데이터 항목을 현재 확보 상태와 함께 정리한다.\n"
        ),
        (
            "| 데이터 항목 | 논문 근거 | 소스(ID) | 현재 상태 | 우선순위 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 역별 혼잡도(%) 정적 프로파일 | 전체 논문 공통 타겟 개념 | "
            "OA-12928(서울시)·9호선 xlsx | **확보** (이 리포트 1~6절) | - |\n"
            "| 역별 시간대별 승하차 인원 | 장려상 상관분석·기상 요소·빅데이터 혼잡도 예측·"
            "탐색적 연구 등 대다수 | `CardSubwayTime`(OA-12252) | **미확보** — 날짜 축이 "
            "있는 유일한 동적 신호. AI/CLAUDE.md 하드 룰에 따라 호출 범위(기간·건수) 사용자 "
            "확인 후 수집 | 최우선 |\n"
            "| 기상 8종(기온·강수량·습도·풍속·체감온도·일사량·풍향 등) | 장려상 상관분석, "
            "기상 요소 예측모델 | 기상청 ASOS/단기예보(README ⑪, ★ URL 미확인) | **미확보** "
            "— `data/EXTERNAL/raw/weather/{asos,forecast,nowcast}/` 폴더만 존재, 실 데이터 "
            "없음 | 높음 |\n"
            "| 공휴일·대체공휴일 특일정보 | 기상 요소 예측모델(RMSE 36%↓ 근거) | 한국천문연구원 "
            "특일 API | **미확보** | 높음 |\n"
            "| 프로야구/축구 경기일정·관중 수 | 기상 요소 예측모델 | KBO/K리그 API·스크래핑 | "
            "**미확보** | 중간 (6주 범위 내 2호선·강남·홍대축 한정이면 경기장 인접 역만 선별 "
            "적용 검토) |\n"
            "| 역사 메타데이터(위경도·출입구 수·환승노선 수·환승유입인원·섬식여부·면적) | "
            "장려상 상관분석(위경도), 빅데이터 추천시스템(출입구·환승·면적), 탐색적 연구"
            "(연관분석 변수) | 서울시 역사 위경도(OA-21232) 등 | **미확보** — 군집화(5.1절)"
            "를 넘어 SHAP류 변수 중요도 분석을 하려면 필요 | 중간 |\n"
            "| 법정 혼잡도 임계치(등급 정의) | 철도안전관리체계 기술기준 고시 | 국토부 고시 "
            "제2023-414호 (수집 대상 아님, 정의 참조) | **확보** (4절에서 라벨링 기준으로 "
            "채택) | - |\n"
            "| 자치구별 상업지구·유동인구 통계 | 지하철 혼잡도 개선방안 탐색적 연구 | 서울시 "
            "통계 사이트 | **미확보** — 6주 범위(강남·홍대축)의 보조 설명 변수 후보, "
            "핵심 경로 아님 | 낮음 |\n"
        ),
        "## 9. 후보 피처 목록\n",
        (
            "8절 데이터가 모두 확보된다는 가정하에, 착석 기회 지수(README 2.1) 학습·검증에 "
            "쓸 피처 후보를 카테고리별로 정리한다. `있음`은 지금 바로 파생 가능, `대기`는 "
            "8절 데이터 확보가 선행돼야 한다.\n"
        ),
        (
            "- **주기성(있음)**: `hour`/`time_slot`, `weekday`, `is_weekend`, "
            "`day_type`(평일/주말/휴일 통합)\n"
            "- **역 구조(대기)**: `station_cluster_id`(5.1절 방식으로 승하차 데이터 확보 후 "
            "재산출), 위경도, 출입구 수, 환승노선 수, 섬식여부\n"
            "- **동적 수요(대기)**: 해당 역 승하차 인원, 이전 역 승하차 인원(재귀적 반영), "
            "직전 시간대 혼잡도(자기회귀 성격)\n"
            "- **기상(대기)**: 체감온도, 시간당 강수량 — 다수 논문에서 상위 중요도로 보고된 "
            "핵심 변수만 우선 채택하고 나머지 6종은 상관 확인 후 선별\n"
            "- **특수성(대기)**: `is_holiday`, 인근 경기장 이벤트 여부·예상 관중 수\n"
            "- **타겟(확보)**: 혼잡도(%) → 법정 임계치(4절) 기준 4단계 등급, 또는 착석 기회 "
            "지수 변환의 입력값\n"
        ),
        "## 10. 다음 단계\n",
        (
            "1. `CardSubwayTime` 확보 — 날짜 축이 있는 유일한 신호라 최우선. 호출 범위"
            "(기간·건수)를 사용자와 먼저 맞춘다(`AI/CLAUDE.md` 하드 룰, 이번 리포트 범위에는 "
            "포함하지 않음).\n"
            "2. 승하차 데이터 확보 후: 같은 역의 시간별 승하차-혼잡도 상관(강한 양의 상관 "
            "예상, 0절 인사이트) 검증, 5.1절 군집을 승하차 기반으로 재산출해 스냅샷 기반 "
            "군집과 일치하는지 비교.\n"
            "3. 기상·특일 데이터 확보(우선순위 순) 후 피처 간 상관·다중공선성 점검, 6절의 "
            "최신성 우선 학습 전략을 실제 RMSE로 검증.\n"
        ),
    ]

    out_path = REPORTS_DIR / "crowd_eda.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    path = generate()
    print(f"리포트 생성 완료: {path}")
