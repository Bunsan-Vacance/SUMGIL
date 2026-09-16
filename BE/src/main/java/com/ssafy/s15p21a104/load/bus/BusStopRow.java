package com.ssafy.s15p21a104.load.bus;

/**
 * bus_stop 한 행. stop_id 는 원천 NODE_ID 그대로 — 버스 도착정보 API 의 stId 와 같은 체계다.
 * 좌표는 원천에 없으면 null (노선별 파일에서 보충한 경기 구간 정류소는 그 파일 좌표).
 */
public record BusStopRow(String stopId, String name, Double lat, Double lng) {
}
