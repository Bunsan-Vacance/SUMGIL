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
     * @param placeNodeId 이 좌표를 나타낼 임시 노드 ID
     * @param placeLat 좌표 위도
     * @param placeLng 좌표 경도
     * @param stationInfos 역·정류장·대여소 좌표 전체(그래프 레지스트리 원본)
     * @param graph 실제 연결 여부 확인용 그래프(임시 엣지 추가 전)
     * @param outgoing true면 좌표→후보 방향(출발지), false면 후보→좌표 방향(도착지)
     * @return 임시 WALK 엣지 목록. 반경 안 후보가 없으면 빈 목록
     */
    public static List<Edge> accessEdges(
            String placeNodeId, double placeLat, double placeLng,
            Map<String, RouteMapper.StationInfo> stationInfos, RouteGraph graph, boolean outgoing) {
        record Candidate(String nodeId, double distanceM) {
        }
        List<Candidate> candidates = new ArrayList<>();
        for (RouteMapper.StationInfo info : stationInfos.values()) {
            if (info.lat() == null || info.lng() == null || !graph.containsNode(info.stationId())) {
                continue;
            }
            double distanceM = GeoDistance.haversineMeters(placeLat, placeLng, info.lat(), info.lng());
            if (distanceM > ACCESS_RADIUS_M) {
                continue;
            }
            candidates.add(new Candidate(info.stationId(), distanceM));
        }
        candidates.sort(Comparator.comparingDouble(Candidate::distanceM));

        List<Edge> edges = new ArrayList<>();
        for (Candidate candidate : candidates.subList(0, Math.min(MAX_ACCESS_CANDIDATES, candidates.size()))) {
            int sec = (int) Math.round(candidate.distanceM() / WalkEdgeBuilder.METERS_PER_SEC);
            edges.add(outgoing
                    ? new Edge(placeNodeId, candidate.nodeId(), WalkEdgeBuilder.WALK_ROUTE_ID, sec, 0, TravelMode.WALK)
                    : new Edge(candidate.nodeId(), placeNodeId, WalkEdgeBuilder.WALK_ROUTE_ID, sec, 0, TravelMode.WALK));
        }
        return edges;
    }
}
