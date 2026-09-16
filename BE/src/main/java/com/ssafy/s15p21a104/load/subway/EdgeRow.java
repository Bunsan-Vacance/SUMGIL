package com.ssafy.s15p21a104.load.subway;

/** 요일·시간대로 펼치기 전의 방향 있는 엣지. SUBWAY 는 route_id 가 line_id 다. */
public record EdgeRow(String fromNode, String toNode, String mode, String routeId, int travelSec, String source) {
}
