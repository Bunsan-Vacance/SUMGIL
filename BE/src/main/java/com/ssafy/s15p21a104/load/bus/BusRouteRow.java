package com.ssafy.s15p21a104.load.bus;

/** bus_route 한 행. route_id 는 원천 ROUTE_ID 그대로 — 버스 도착정보 API 의 busRouteId 와 같은 체계다. */
public record BusRouteRow(String routeId, String name) {
}
