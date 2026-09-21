package com.ssafy.s15p21a104.domain.route.walk;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder.Stop;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 서로 다른 유형(역·대여소·정류장) 쌍의 WALK 엣지 생성. 순수 로직이며 DB에 접근하지 않는다.
 *
 * <p>도보 속도로 직선거리를 나누어 소요를 산정한다.
 * 좌표 없는 정점·반경 밖 쌍은 엣지를 만들지 않는다(값 채우기 금지).
 */
public final class WalkEdgeBuilder {

    /** WALK 엣지 연결 반경(m). 이보다 먼 쌍은 잇지 않는다. */
    public static final double RADIUS_M = 500.0;

    /** 도보 속도(m/s). 분당 67m. */
    public static final double METERS_PER_SEC = 67.0 / 60.0;

    /**
     * 직선→실제 도보 우회율 (S15P21A104-216 배치).
     * FE는 실제 도보 경로(횡단보도 등)를 렌더링하지만 엔진 비용은 직선 거리라,
     * 돌아가는 구간이 최단으로 찍히던 문제를 보정한다. 도심 보행 문헌값 1.2~1.4의
     * 중간값이며, 카카오 실측 표본으로 재보정해야 한다. 반경 판정은 직선 그대로
     * 두고(연결성 유지) 비용에만 얹는다.
     */
    public static final double CIRCUITY = 1.3;

    /** WALK 엣지의 routeId. 노선 전환(환승 집계·페널티) 기준이 된다. */
    public static final String WALK_ROUTE_ID = "WALK";

    /** 지구 반경(m). 하버사인용. */
    private static final double EARTH_R = 6_371_000.0;

    /**
     * 후보 사전 필터용 격자 한 변(도). {@link #RADIUS_M}보다 충분히 커서 인접 3x3 셀만
     * 봐도 반경 안 쌍을 놓치지 않는다(정류장이 만 단위라 전수 비교(N*M)가 비싸질 수 있어
     * bbox pre-filter로 후보를 좁힌다, S15P21A104-188).
     */
    private static final double CELL_DEG = 0.01;

    private WalkEdgeBuilder() {
    }

    /**
     * 역↔대여소 쌍만 잇는다(하위 호환). 역↔정류장·대여소↔정류장까지 필요하면
     * {@link #build(Map, Map, Map)}을 쓴다.
     *
     * @param stations 역 (id → 좌표)
     * @param rentals 대여소 (id → 좌표)
     * @return WALK 엣지 목록. 해당 쌍이 없으면 빈 목록
     */
    public static List<Edge> build(Map<String, Stop> stations, Map<String, Stop> rentals) {
        return build(stations, rentals, Map.of());
    }

    /**
     * 서로 다른 유형(역·대여소·정류장) 쌍 중 반경 안을 양방향 WALK 엣지로 잇는다
     * (S15P21A104-188). 같은 유형끼리(정류장↔정류장 등)는 잇지 않는다 — 그건 각 수단
     * 고유 엣지(BUS 등)의 몫이다.
     *
     * @param stations 역 (id → 좌표)
     * @param rentals 대여소 (id → 좌표)
     * @param busStops 버스 정류장 (id → 좌표)
     * @return WALK 엣지 목록. 해당 쌍이 없으면 빈 목록
     */
    public static List<Edge> build(
            Map<String, Stop> stations, Map<String, Stop> rentals, Map<String, Stop> busStops) {
        List<Edge> edges = new ArrayList<>();
        edges.addAll(connect(stations, rentals));
        edges.addAll(connect(stations, busStops));
        edges.addAll(connect(rentals, busStops));
        return edges;
    }

    /** {@code as}·{@code bs} 사이 반경 안 쌍을 양방향 WALK 엣지로 잇는다. {@code bs}를 격자에 담아 후보를 좁힌다. */
    private static List<Edge> connect(Map<String, Stop> as, Map<String, Stop> bs) {
        List<Edge> edges = new ArrayList<>();
        if (as == null || bs == null || as.isEmpty() || bs.isEmpty()) {
            return edges;
        }
        Map<CellKey, List<Stop>> grid = new HashMap<>();
        for (Stop b : bs.values()) {
            if (!hasCoord(b)) {
                continue;
            }
            grid.computeIfAbsent(cellOf(b), k -> new ArrayList<>()).add(b);
        }
        for (Stop a : as.values()) {
            if (!hasCoord(a)) {
                continue;
            }
            CellKey center = cellOf(a);
            for (int dLat = -1; dLat <= 1; dLat++) {
                for (int dLng = -1; dLng <= 1; dLng++) {
                    List<Stop> bucket = grid.get(new CellKey(center.latIdx() + dLat, center.lngIdx() + dLng));
                    if (bucket == null) {
                        continue;
                    }
                    for (Stop b : bucket) {
                        double dist = distanceM(a, b);
                        if (dist > RADIUS_M) {
                            continue;
                        }
                        int sec = (int) Math.round(dist * CIRCUITY / METERS_PER_SEC);
                        edges.add(new Edge(a.id(), b.id(), WALK_ROUTE_ID, sec, 0, TravelMode.WALK));
                        edges.add(new Edge(b.id(), a.id(), WALK_ROUTE_ID, sec, 0, TravelMode.WALK));
                    }
                }
            }
        }
        return edges;
    }

    private static CellKey cellOf(Stop stop) {
        return new CellKey((int) Math.floor(stop.lat() / CELL_DEG), (int) Math.floor(stop.lng() / CELL_DEG));
    }

    private record CellKey(int latIdx, int lngIdx) {
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
