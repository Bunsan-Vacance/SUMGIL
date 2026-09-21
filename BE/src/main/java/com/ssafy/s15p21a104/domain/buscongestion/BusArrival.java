package com.ssafy.s15p21a104.domain.buscongestion;

/**
 * 한 정류소에 다음으로 도착하는 그 노선 버스의 혼잡 등급과 도착까지 남은 초 (S15P21A104-297).
 *
 * <p>원천 응답은 노선마다 첫째·둘째 도착 버스를 접미사 1·2 로 나눠 주는데 <b>첫째만 쓴다</b> —
 * 사용자가 실제로 탈 버스이기 때문이다.
 *
 * @param routeId    {@code busRouteId}. 우리 {@code bus_route.route_id} 와 같은 체계다
 * @param grade      혼잡 등급
 * @param arrivalSec 도착까지 남은 초({@code traTime1}). 원천이 0 이하를 주면
 *                   {@link #UNKNOWN_ARRIVAL_SEC} 로 바꿔 정렬에서 맨 뒤로 민다 —
 *                   "곧 온다" 로 착각해 그 버스를 구간 대푯값으로 뽑으면 안 된다
 */
public record BusArrival(String routeId, BusCongestionGrade grade, int arrivalSec) {

    /** 도착 시각을 모를 때 쓰는 값. 정렬에서 항상 뒤로 간다. */
    public static final int UNKNOWN_ARRIVAL_SEC = Integer.MAX_VALUE;

    public BusArrival {
        if (routeId == null || routeId.isBlank()) {
            throw new IllegalArgumentException("routeId 는 비어 있을 수 없다");
        }
        if (grade == null) {
            throw new IllegalArgumentException("grade 는 null 일 수 없다");
        }
        if (arrivalSec <= 0) {
            arrivalSec = UNKNOWN_ARRIVAL_SEC;
        }
    }

    /** 도착이 더 이른 쪽. 같으면 {@code this}. */
    public BusArrival soonerOf(BusArrival other) {
        return other != null && other.arrivalSec < arrivalSec ? other : this;
    }
}
