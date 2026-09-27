package com.ssafy.s15p21a104.domain.route.dto.response;

import java.util.List;

public record RouteSearchResponse(
        RouteType routeType,
        Double totalMinutes,
        List<RouteLegResponse> legs,
        RouteSource source,
        /**
         * 경로 전체의 실제 이동 거리 합(m, S15P21A104-150/FE-175 항목8). legs 전부가
         * {@code distanceMeters}를 확보한 경우에만 값이 있다 — 하나라도 없으면 {@code null}
         * (0이나 일부 합으로 대체하지 않음).
         */
        Double totalDistanceMeters,
        /**
         * 환승 횟수(S15P21A104-150/FE-175 항목8, S15P21A104-213 T1·214).
         * 실제 탑승 수단(BIKE·BUS·SUBWAY) 전환 횟수다. WALK와 TRANSFER leg 자체는
         * 세지 않으며, 명시 TRANSFER는 다음 실제 탑승 경계에서 한 번 보조한다. 따라서
         * TRANSFER leg 수와 다를 수 있다.
         */
        Integer transferCount,
        /**
         * 혼잡 예측(S15P21A104-236, FE-BE 통합 계약 §2). null이면 미제공 —
         * FE는 {@code 예측 정보 없음}을 표시한다.
         */
        CongestionPrediction congestionPrediction
) {
}
