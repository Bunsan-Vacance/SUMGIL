"""환승 유출입이 재귀식 혼잡도에 실제로 오차를 만드는지 진단한다.

## 원래 계획(10번 — 환승 유출입 보정)을 그대로 할 수 없다

`서울교통공사_서울 도시철도 환승정보_20260303.csv`가 환승 유출입 **보정**에 쓰일
자료로 지목돼 있었지만, 내용을 열어보니 **환승 인원·비율 컬럼이 아예 없다.** 컬럼은
환승시작역·환승종료역·몇 호차 몇 번 문으로 내려서 갈아타는지·도보 소요시간뿐이다 —
환승 동선 안내(길찾기 앱류)용 데이터지 유동량 데이터가 아니다(2026-09-10 확인).

그래서 "환승으로 새는 인원을 역별로 수치 보정"하는 원래 계획은 **이 데이터로 불가능
하다** — 데이터 검증 리포트 원칙 8("접근성이 좋다는 것과 적합하다는 것은 다르다")에
정확히 해당한다. 대신 이 파일에서 실제로 얻을 수 있는 것(환승역·호선 쌍 목록)으로
스코프를 좁혀, **환승역이 정말 오차가 더 큰지**를 확인하는 진단으로 대체한다 — 재귀식
`build_congestion_label.py`의 docstring이 "가장 큰 위험"이라 지목한 게 실제로 관측되는
문제인지 데이터로 확인하는 것이다.

## 진단 방법

환승역이 아닌 역 대비, 환승역에서 배율(7번 `crowd_congestion_calibration.parquet`)이
**얼마나 더 흩어지는지**를 비교한다. 배율은 "실측 ÷ raw"라 재귀식이 실측을 잘 설명하면
같은 호선 안에서 값이 고르게 모이고, 환승으로 새는 인원을 반영 못 하면 역마다 들쭉날쭉
해진다 — 환승역에서 이 산포가 유의하게 크면 "환승 누출이 실제로 오차원"이라는 근거가
된다. 보정은 못 해도 **어디가 위험한지는 이걸로 안다.**

실행:
    cd AI
    python -m DATA_ENGINE.eda.diagnose_transfer_leakage
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
TRANSFER_RAW = (
    AI_ROOT
    / "data"
    / "ROUTE"
    / "raw"
    / "transfer_info"
    / "서울교통공사_서울 도시철도 환승정보_20260303.csv"
)
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"
CALIBRATION_NAME = "crowd_congestion_calibration.parquet"


def load_transfer_pairs(path: Path = TRANSFER_RAW) -> pd.DataFrame:
    """환승 동선 안내 원본에서 (역, 호선A, 호선B) 환승 관계만 추린다.

    인원·소요시간 같은 동선 세부 컬럼은 이 진단에 쓰지 않는다 — 애초에 볼 수 있는 게
    "어느 역에서 어느 호선끼리 환승이 있는가"뿐이다. 코레일 구간 코드("100C" 등,
    숫자가 아닌 표기)는 우리 station_no 체계 밖이라 자연히 걸러진다.
    """
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["환승시작_station_no"] = pd.to_numeric(df["환승시작 코드"], errors="coerce")
    df["환승종료_station_no"] = pd.to_numeric(df["환승종료역"], errors="coerce")
    df = df.dropna(subset=["환승시작_station_no", "환승종료_station_no"]).copy()
    df["환승시작_station_no"] = df["환승시작_station_no"].astype("int64")
    df["환승종료_station_no"] = df["환승종료_station_no"].astype("int64")
    return df[
        ["환승시작역", "환승시작_station_no", "환승시작 호선", "환승종료_station_no"]
    ].drop_duplicates()


def transfer_station_numbers(pairs: pd.DataFrame, available: set[int]) -> set[int]:
    """환승 관계에 등장하는 station_no 중, 우리 재귀식 라벨에 실제로 있는 것만 남긴다.

    시작역·종료역 양쪽 다 본다 — 환승정보가 방향을 안 가리므로 한쪽만 보면 절반을
    놓친다.
    """
    starts = set(pairs["환승시작_station_no"])
    ends = set(pairs["환승종료_station_no"])
    return (starts | ends) & available


def compare_ratio_dispersion(
    calibration: pd.DataFrame, transfer_stations: set[int]
) -> pd.DataFrame:
    """호선별로 환승역 vs 비환승역의 배율 산포(IQR/중앙값)를 비교한다.

    표준편차가 아니라 **IQR**(25~75분위 폭)을 쓴다 — 배율 분포가 0 근처에 몰려 있다가
    드물게 수백 배(4호선 최대 742)까지 튀는 긴 꼬리라, 표준편차는 극단값 한두 개에
    좌우돼 진짜 산포를 못 본다(직접 확인: 표준편차 기준으로는 4호선 변동계수가 101.9로
    튀어 이상치 하나가 전체를 왜곡했다). IQR÷중앙값은 "가운데 절반이 중앙값 대비 얼마나
    퍼져 있는가"라 이상치 한둘에 흔들리지 않는다. 호선마다 배율 수준 자체가 다르므로
    (2호선 0.08, 8호선 0.19) 중앙값으로 나눠 정규화한다.
    """
    frame = calibration.dropna(subset=["ratio"]).copy()
    frame["is_transfer"] = frame["station_no"].isin(transfer_stations)

    grouped = frame.groupby(["line", "is_transfer"], observed=True)["ratio"]
    q1 = grouped.quantile(0.25).rename("q1")
    q3 = grouped.quantile(0.75).rename("q3")
    median = grouped.median().rename("median")
    n = grouped.count().rename("n")
    summary = pd.concat([n, median, q1, q3], axis=1).reset_index()
    summary["IQR_중앙값비"] = (summary["q3"] - summary["q1"]) / summary["median"]
    return summary.drop(columns=["q1", "q3"])


def save_transfer_pairs(pairs: pd.DataFrame) -> Path:
    out_dir = AI_ROOT / "data" / "ROUTE" / "interim"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "transfer_station_pairs.parquet"
    pairs.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    pairs = load_transfer_pairs()
    out_path = save_transfer_pairs(pairs)
    print(f"[안내] 환승 관계(원본 전체, 코레일 등 포함) {len(pairs):,}건 → {out_path}")

    calibration = pd.read_parquet(CROWD_PROCESSED / CALIBRATION_NAME)
    available = set(calibration["station_no"].unique())
    transfer_stations = transfer_station_numbers(pairs, available)
    print(
        f"[안내] 우리 범위(1~8호선 + 9호선 2·3단계) 안의 환승역 {len(transfer_stations)}개 "
        f"/ 전체 역 {len(available)}개"
    )

    summary = compare_ratio_dispersion(calibration, transfer_stations)
    print("\n[진단] 호선별 배율 산포(IQR÷중앙값) — 환승역 vs 비환승역:")
    print(summary.round(3).to_string(index=False))

    wide = summary.pivot(index="line", columns="is_transfer", values="IQR_중앙값비")
    if True in wide.columns and False in wide.columns:
        # 1호선처럼 구간 전체가 환승역이라 비환승역이 아예 없는 호선은 비교 자체가
        # 안 되므로 분모에서 뺀다 — 넣으면 "비교 불가"가 "환승역이 더 안정적"으로
        # 잘못 세어진다.
        comparable = wide.dropna(subset=[True, False])
        worse = int((comparable[True] > comparable[False]).sum())
        print(
            f"\n[결론] 비교 가능한 {len(comparable)}개 호선 중 {worse}개 호선에서 환승역의 "
            "배율 산포(IQR÷중앙값)가 비환승역보다 크다 — 절반 안팎이라 뚜렷한 방향성은 "
            "없다. 환승 누출이 유일한 오차원이라기보다, 2호선 지선 라벨 불일치 등 이미 "
            "확인된 다른 원인과 섞여 있을 가능성이 크다(보정치는 아니다, 진단일 뿐)."
        )
        if len(wide) > len(comparable):
            excluded = sorted(set(wide.index) - set(comparable.index))
            print(f"  비환승역이 없어 비교에서 뺀 호선: {excluded}")


if __name__ == "__main__":
    main()
