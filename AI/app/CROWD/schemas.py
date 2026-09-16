"""CROWD 조회 API 응답 모델.

숫자를 낼 수 없는 셀은 값을 채우지 않고 `data_status`로 알린다(원칙 8):
- `ok` — 예측·배율 모두 정상
- `no_lookup` — 학습 구간에 없는 요일유형×역×시간대라 기준선 자체가 없음
- `calibration_fallback` — 1~8호선 공휴일이라 **일요일 배율**을 빌려 쓴 셀(146). 값은 있지만 그 날의
  배율로 낸 값이 아니라는 뜻이라 화면에서 구분한다(공휴일 다이어가 일요일 다이어와 같다는 근거는
  `validation/CROWD/congestion-criteria-check/RESULTS.md` 2절)
- `segment_truncated` — 절단 구간(코레일·인천교통공사 직결 구간이 우리 원천에 없는 1·3·4·7호선 본선,
  2호선 신정지선)의 종점 링크. 재차인원이 구조적으로 0이라 배율도 산출되지 않는다(146의 1호선 전용
  `line1_truncated`를 199에서 전 절단 구간으로 넓혔다). 199의 경계 유입 반영으로 대부분 `ok`가 됐고,
  상수를 못 구한 셀만 이 상태로 남는다
- `no_calibration` — 그 밖의 배율표 결측(결번 역, 대응 못 한 2호선 지선 셀)
- `no_data` — 그 날짜의 예측 표가 아직 생성되지 않음(배치 미실행)

`pred_clipped`(197): 그 슬롯의 승차·하차 예측 중 하나라도 음수라 0으로 클립됐는지. 인원은 항상
0 이상(물리 제약)이라 표에는 클립된 값만 실리고, 이 필드는 그 사실을 감사용으로 노출한다.
"""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, Field


class SlotCongestion(BaseModel):
    time_slot_30min: str = Field(description="30분 슬롯 시작 시각, 예: '08:30'")
    direction: str = Field(description="상선/하선 또는 내선/외선(2호선)")
    congestion_pct: float | None = Field(
        description="보정 혼잡도(%). 정원 100% 기준, 결측이면 null"
    )
    grade: int | None = Field(
        description="등급 0..N (임계치는 meta.grade_thresholds). 결측이면 null"
    )
    data_status: str
    pred_clipped: bool = Field(
        description="승차·하차 예측 중 하나라도 음수라 0으로 클립됐는지(197)"
    )


class StationCongestionResponse(BaseModel):
    date: date_type
    station_no: int
    station_name: str | None
    line: str | None
    train_capacity: int | None
    predictor_version: str | None
    lag1d_available: bool | None = Field(
        description="전날 실측이 있었는지. False면 1주 전 시차만으로 예측"
    )
    slots: list[SlotCongestion]


class LineStationSnapshot(BaseModel):
    station_no: int
    station_name: str | None
    direction: str
    congestion_pct: float | None
    grade: int | None
    data_status: str
    pred_clipped: bool = Field(
        description="승차·하차 예측 중 하나라도 음수라 0으로 클립됐는지(197)"
    )


class LineCongestionResponse(BaseModel):
    date: date_type
    line: str
    time_slot_30min: str
    stations: list[LineStationSnapshot]


class CrowdMetaResponse(BaseModel):
    available_dates: list[date_type]
    grade_thresholds: list[float]
    predictor: str | None
    predictor_version: str | None
    generated_at: str | None
    status_counts: dict[str, int] | None
    topology_gaps: list[dict] | None
