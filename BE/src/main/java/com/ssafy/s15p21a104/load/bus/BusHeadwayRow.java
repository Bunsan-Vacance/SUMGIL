package com.ssafy.s15p21a104.load.bus;

/**
 * bus_route 의 배차간격 갱신 한 행.
 *
 * @param routeId    노선 ID. 원천 {@code busRouteId} 이고 {@code bus_route.route_id}(OA-1095 의 ROUTE_ID)와 같은 체계다
 *                   — 2026-09-17 실측으로 450개 노선의 ID 가 양쪽에서 일치했다
 * @param headwayMin 배차간격(분). <b>원천의 0 은 null 로 바꾼다</b> — 0 은 "배차 0분" 이 아니라
 *                   "그 시각에 운행 중이 아니라 모른다" 는 뜻이다. 0 을 그대로 적재하면 그래프가 대기시간을 0초로
 *                   계산해 그 노선이 무조건 최단 경로로 뽑힌다
 */
public record BusHeadwayRow(String routeId, Integer headwayMin) {
}
