package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/**
 * 좌표 접근 임시 엣지 생성(S15P21A104-213 T4).
 *
 * <p>{@code RouteSearchService}에서 분리했다. 좌표 주변 보행 접근 가능한
 * 역·정류장·대여소를 반경 안에서 가까운 순으로 최대 상한까지 찾아 임시 WALK
 * 엣지로 만든다. 순수 로직이며 DB에 접근하지 않는다.
 */
public final class CoordinateAccessEdges {

    /** 좌표→역·정류장·대여소 접근 간선 연결 반경(m). {@link WalkEdgeBuilder}와 같은 값. */
    public static final double ACCESS_RADIUS_M = 500.0;

    /** 접근 후보 상한(가까운 순). 무제한 탐색을 막아 탐색량을 억제한다(S15P21A104-187 완료기준). */
    public static final int MAX_ACCESS_CANDIDATES = 5;

    private CoordinateAccessEdges() {
    }

    /**
     * 좌표 주변 보행 접근 가능한 역·정류장·대여소를 반경 {@value #ACCESS_RADIUS_M}m 안에서
     * 가까운 순으로 최대 {@value #MAX_ACCESS_CANDIDATES}개 찾아 임시 WALK 엣지로 만든다.
     * 실제 그래프에 연결돼 있지 않은 정점(좌표만 있고 고립된 경우)은 후보에서 뺀다 — 접근은
     * 됐는데 그 다음이 막힌 후보를 만들지 않기 위함이다.
     *
     * <p>최근접 역 최소 1곳을 보장한다(S15P21A104-231). 정류장 밀집지에서 거리순 절단으로
     * 역이 탈락하면 역 직결 탐색 자체가 일어나지 않으므로, 역 1곳을 먼저 확보하고 나머지를
     * 거리순으로 채운다. 전체 상한은 그대로 둔다.
     *
     * @param placeNodeId 이 좌표를 나타낼 임시 노드 ID
     * @param placeLat 좌표 위도
     * @param placeLng 좌표 경도
     * @param stationInfos 역·정류장·대여소 좌표 전체(그래프 레지스트리 원본)
     * @param graph 실제 연결 여부 확인용 그래프(임시 엣지 추가 전)
     * @param outgoing true면 좌표→후보 방향(출발지), false면 후보→좌표 방향(도착지)
     * @param stationIds 역 ID 집합. null 허용
     * @return 임시 WALK 엣지 목록. 반경 안 후보가 없으면 빈 목록
     */
    public static List<Edge> accessEdges(
            String placeNodeId, double placeLat, double placeLng,
            Map<String, RouteMapper.StationInfo> stationInfos, RouteGraph graph, boolean outgoing,
            java.util.Set<String> stationIds) {
        record Candidate(String nodeId, double distanceM) {
        }
        List<Candidate> stations = new ArrayList<>();
        List<Candidate> others = new ArrayList<>();
        for (RouteMapper.StationInfo info : stationInfos.values()) {
            if (info.lat() == null || info.lng() == null || !graph.containsNode(info.stationId())) {
                continue;
            }
            double distanceM = GeoDistance.haversineMeters(placeLat, placeLng, info.lat(), info.lng());
            if (distanceM > ACCESS_RADIUS_M) {
                continue;
            }
            Candidate candidate = new Candidate(info.stationId(), distanceM);
            if (stationIds != null && stationIds.contains(info.stationId())) {
                stations.add(candidate);
            } else {
                others.add(candidate);
            }
        }
        stations.sort(Comparator.comparingDouble(Candidate::distanceM));
        others.sort(Comparator.comparingDouble(Candidate::distanceM));

        List<Candidate> picked = new ArrayList<>();
        if (!stations.isEmpty()) {
            picked.add(stations.get(0));
        }
        for (Candidate candidate : others) {
            if (picked.size() >= MAX_ACCESS_CANDIDATES) {
                break;
            }
            picked.add(candidate);
        }
        for (int i = 1; i < stations.size() && picked.size() < MAX_ACCESS_CANDIDATES; i++) {
            picked.add(stations.get(i));
        }

        List<Edge> edges = new ArrayList<>();
        for (Candidate candidate : picked) {
            // 비용에만 우회율을 얹는다 — 반경·정렬은 직선 그대로(연결성·순서 보존).
            // WalkEdgeBuilder와 같은 상수라 도보 시간이 그래프 안팎에서 일치한다.
            int sec = (int) Math.round(
                    candidate.distanceM() * WalkEdgeBuilder.CIRCUITY / WalkEdgeBuilder.METERS_PER_SEC);
            edges.add(outgoing
                    ? new Edge(placeNodeId, candidate.nodeId(), WalkEdgeBuilder.WALK_ROUTE_ID, sec, 0, TravelMode.WALK)
                    : new Edge(candidate.nodeId(), placeNodeId, WalkEdgeBuilder.WALK_ROUTE_ID, sec, 0, TravelMode.WALK));
        }
        return edges;
    }
}
