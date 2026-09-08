package com.ssafy.s15p21a104.load.subway;

import java.util.Set;

/** station 테이블 1행. 물리 역 하나이며 소속 노선은 edge_time 의 route_id 로만 표현되므로 여기서는 참고용이다. 좌표는 원천에 없으면 null 로 둔다 (채워 넣지 않는다). */
public record StationRow(String stationId, String name, Double lat, Double lng, Set<String> lineIds) {
}
