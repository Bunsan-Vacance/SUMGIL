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
         * 환승 횟수(S15P21A104-150/FE-175 항목8). 현재는 routeId 전환마다 삽입되는 TRANSFER
         * leg 수를 그대로 센다 — WALK·BIKE 접근/반납 경계도 포함하는 현재 정의 그대로이며,
         * "대중교통 환승만" 세는 정의로 좁히는 건 별도 정책 합의(FE-175 항목7, 전우석 영역) 대상이다.
         */
        Integer transferCount
) {
}
