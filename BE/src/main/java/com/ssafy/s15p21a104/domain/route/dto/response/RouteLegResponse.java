package com.ssafy.s15p21a104.domain.route.dto.response;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;

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
        String routeName,
        /**
         * BUS leg 운행 노선 후보(S15P21A104-234). 정규 구간이라 노선 선택을 미루고 목록으로 싣는다.
         * 비BUS leg는 null. FE 표시용이며 탐색·집계에 쓰지 않는다.
         */
        List<RouteOptionResponse> routeOptions,
        /**
         * BUS leg 실시간 혼잡 등급(S15P21A104-297). {@code RELAXED}·{@code NORMAL}·{@code CONGESTED}·
         * {@code SATURATED} 중 하나이며 FE {@code SegmentCongestionGrade} 와 같은 4값이다.
         *
         * <p>구간 단위 하나다 — {@link #routeOptions} 후보별 값이 아니라 그 승차 정류소에 <b>가장 먼저
         * 오는</b> 버스 기준이다. <b>BUS leg 이면서 지금 출발 검색일 때만</b> 채워진다. 미래 시각 검색·
         * 경기/인천 버스·운행종료 노선·외부 실패·예산 소진은 모두 null 이고, FE 는 "정보 없음" 으로 둔다.
         *
         * <p>퍼센트가 아니라 등급인 이유: 원천이 4단계 코드라 퍼센트로 바꾸면 안 잰 숫자를 화면에 띄우게
         * 된다. FE 계약 문서 {@code .claude/handoff/TO_FE-bus-congestion-01.md} 참고.
         */
        String congestionGrade
) {

    /**
     * 혼잡 등급 없이 만드는 기존 형태(S15P21A104-234 까지의 16인자). 등급은 {@code RouteNameResolver}
     * 가 후처리로 붙이므로 매퍼·기하 보강 단계는 이 생성자를 쓴다.
     */
    public RouteLegResponse(
            TravelMode mode,
            String fromNodeId, String fromNodeName, Double fromLat, Double fromLng,
            String toNodeId, String toNodeName, Double toLat, Double toLng,
            String routeId, Double minutes,
            MultiLineStringResponse geometry, String geometryStatus,
            Double distanceMeters, String routeName,
            List<RouteOptionResponse> routeOptions) {
        this(mode, fromNodeId, fromNodeName, fromLat, fromLng, toNodeId, toNodeName, toLat, toLng,
                routeId, minutes, geometry, geometryStatus, distanceMeters, routeName, routeOptions, null);
    }

    /** 같은 leg 에 혼잡 등급만 바꿔 끼운다. */
    public RouteLegResponse withCongestionGrade(String grade) {
        return new RouteLegResponse(mode, fromNodeId, fromNodeName, fromLat, fromLng,
                toNodeId, toNodeName, toLat, toLng, routeId, minutes,
                geometry, geometryStatus, distanceMeters, routeName, routeOptions, grade);
    }
}
