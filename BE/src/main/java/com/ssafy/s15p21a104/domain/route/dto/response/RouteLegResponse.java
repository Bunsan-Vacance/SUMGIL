package com.ssafy.s15p21a104.domain.route.dto.response;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;

public record RouteLegResponse(
        TravelMode mode,
        String fromNodeId,
        String fromNodeName,
        Double fromLat,
        Double fromLng,
        String toNodeId,
        String toNodeName,
        Double toLat,
        Double toLng,
        String routeId,
        Double minutes,
        /** KTDB 실선로 좌표(미승인 필드). 매칭 안 되면 null — {@link #geometryStatus} 참고. */
        MultiLineStringResponse geometry,
        /** "available" | "unavailable". */
        String geometryStatus,
        /**
         * 실제 이동 경로 기준 거리(m, S15P21A104-150/FE-175 항목8). {@link #geometry}가 있을 때만
         * 그 좌표를 따라 계산한다 — 직선거리로 대체하지 않으며, 미확보면 {@code null}(선택 필드).
         */
        Double distanceMeters,
        /** 사람이 읽는 노선 이름(버스 번호·지하철 노선명 등, S15P21A104-150/FE-175 항목8). 미확보면 {@code null}. */
        String routeName
) {
}
