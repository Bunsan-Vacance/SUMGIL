package com.ssafy.s15p21a104.domain.route.bike;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder.Stop;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 대여소↔대여소 BIKE 엣지 생성. 순수 로직이며 DB에 접근하지 않는다.
 *
 * <p>역↔대여소 접근은 {@link WalkEdgeBuilder}가 맡고, 자전거 이동 본선만 잇는다.
 * 반경·속도는 {@link BikeEdgeBuilder}와 같은 값을 쓴다(2026-09-11 판단 (a)).
 * 좌표 없는 정점·반경 밖 쌍은 엣지를 만들지 않는다(값 채우기 금지).
 */
public final class BikeRentalEdgeBuilder {

    private BikeRentalEdgeBuilder() {
    }

    /**
     * 대여소 쌍 중 반경 안을 양방향 BIKE 엣지로 잇는다.
     *
     * @param rentals 대여소 (id → 좌표)
     * @return BIKE 엣지 목록. 해당 쌍이 없으면 빈 목록
     */
    public static List<Edge> build(Map<String, Stop> rentals) {
        List<Edge> edges = new ArrayList<>();
        if (rentals == null) {
            return edges;
        }
        List<Stop> stops = new ArrayList<>(rentals.values());
        for (int i = 0; i < stops.size(); i++) {
            if (!BikeEdgeBuilder.hasCoord(stops.get(i))) {
                continue;
            }
            for (int j = i + 1; j < stops.size(); j++) {
                if (!BikeEdgeBuilder.hasCoord(stops.get(j))) {
                    continue;
                }
                double dist = BikeEdgeBuilder.distanceM(stops.get(i), stops.get(j));
                if (dist > BikeEdgeBuilder.RADIUS_M) {
                    continue;
                }
                int sec = (int) Math.round(dist / BikeEdgeBuilder.METERS_PER_SEC);
                edges.add(new Edge(stops.get(i).id(), stops.get(j).id(),
                        BikeEdgeBuilder.BIKE_ROUTE_ID, sec, 0, TravelMode.BIKE));
                edges.add(new Edge(stops.get(j).id(), stops.get(i).id(),
                        BikeEdgeBuilder.BIKE_ROUTE_ID, sec, 0, TravelMode.BIKE));
            }
        }
        return edges;
    }
}
