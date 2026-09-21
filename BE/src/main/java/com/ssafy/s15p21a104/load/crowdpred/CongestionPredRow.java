package com.ssafy.s15p21a104.load.crowdpred;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * {@code congestion_pred} 한 행 (S15P21A104-305). AI CROWD 배치의 링크 단위 예측이고
 * 날짜 × 링크(from→to) × 방향 × 30분 슬롯마다 하나다.
 *
 * @param predDate         대상 날짜(KST)
 * @param fromStationId    링크 시작 역. 원천의 역번호를 우리 {@code station.station_id} 로 바꾼 값이다
 *                         — 환승역은 노선별 역사코드 중 최솟값으로 합쳐진다(4호선 서울역 426 → 150)
 * @param toStationId      링크 끝 역. 종점은 원천에서 행 자체가 만들어지지 않는다
 * @param lineId           {@code line.line_id}. 원천의 {@code "1호선"} 을 {@code "1001"} 로 바꾼 값
 * @param direction        {@code 상선}/{@code 하선}/{@code 내선}/{@code 외선}. <b>원천 값을 그대로 둔다</b> —
 *                         2호선이라도 지선 구간은 상선/하선으로 온다(AI 통지 07). 우리가 재해석하지 않는다
 * @param timeSlot         30분 슬롯 0~47. <b>48개가 다 오지 않는다</b> — 운행 없는 새벽은 행이 없다(실측 39종)
 * @param level            보정 혼잡도 %. <b>결측이면 null</b> — {@code dataStatus} 가 이유를 말한다.
 *                         상한이 없어 100 을 넘는 값도 그대로 담는다
 * @param dataStatus       {@code ok}·{@code calibration_fallback}·{@code segment_truncated}·
 *                         {@code no_calibration}·{@code no_lookup}
 * @param predSource       {@code model}·{@code lookup_negative}·{@code lookup_line9}.
 *                         {@code lookup_*} 는 모델 예측을 그대로 쓰지 않은 셀이다
 * @param predictorVersion 그 행을 만든 예측기. <b>행 단위 열</b>이라 같은 날짜 표 안에서도 다르다
 *                         (9호선만 {@code lookup:line9_…}). 실값이 67자라 V8 에서 128 로 넓혔다
 */
public record CongestionPredRow(LocalDate predDate, String fromStationId, String toStationId, String lineId,
                                String direction, int timeSlot, BigDecimal level,
                                String dataStatus, String predSource, String predictorVersion) {
}
