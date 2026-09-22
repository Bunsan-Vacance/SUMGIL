package com.ssafy.s15p21a104.domain.route.bike;

import java.util.Objects;

/**
 * 자전거 기하 유틸. 순수 로직이며 DB에 접근하지 않는다.
 *
 * <p>역↔대여소 엣지 생성({@code build})은 S15P21A104-122에서 접근 수단이 도보로 확정되며
 * 폐기됐다. 이 클래스는 대여소↔대여소({@link BikeRentalEdgeBuilder})·역↔대여소
 * ({@link com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder})가 공유하는
 * 좌표 정점·하버사인·속도·반경 상수만 남긴다.
 */
public final class BikeEdgeBuilder {

    /** BIKE 엣지 연결 반경(m). 이보다 먼 쌍은 잇지 않는다. */
    public static final double RADIUS_M = 1000.0;

    /**
     * 대여 1회(연속 BIKE 구간) 상한(초) — 1km ÷ 15km/h = 240초(5부 T3 결정: act 총거리 1km 상수).
     * 초과하는 연속 자전거 구간은 접근·이탈 closure·엔진 이완·후보 필터에서 제외한다.
     */
    public static final int MAX_ACT_SEC = 240;

    /** 자전거 속도(m/s). 15km/h. */
    public static final double METERS_PER_SEC = 15_000.0 / 3600.0;

    /** BIKE 엣지의 routeId. 노선 전환(환승 집계·페널티) 기준이 된다. */
    public static final String BIKE_ROUTE_ID = "BIKE";

    /** 지구 반경(m). 하버사인용. */
    private static final double EARTH_R = 6_371_000.0;

    /** 좌표 보유 정점. 위도·경도 null 허용(없으면 제외). */
    public record Stop(String id, Double lat, Double lng) {
        public Stop {
            Objects.requireNonNull(id, "id");
        }
    }

    private BikeEdgeBuilder() {
    }

    static boolean hasCoord(Stop stop) {
        return stop.lat() != null && stop.lng() != null;
    }

    static double distanceM(Stop a, Stop b) {
        double dLat = Math.toRadians(b.lat() - a.lat());
        double dLng = Math.toRadians(b.lng() - a.lng());
        double h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(a.lat())) * Math.cos(Math.toRadians(b.lat()))
                * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return 2 * EARTH_R * Math.asin(Math.sqrt(h));
    }
}
