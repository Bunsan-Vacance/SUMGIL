package com.ssafy.s15p21a104.load.subway;

/** edge_time 테이블 1행. 복합 기본키는 (from, to, mode, route, dow, slot). */
public record EdgeTimeRow(String fromNode, String toNode, String mode, String routeId,
                          int dowType, int timeSlot, int travelSec, int waitSec, String source) {
}
