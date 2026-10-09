package com.ssafy.s15p21a104.domain.station.service;

import com.ssafy.s15p21a104.domain.route.repository.RouteEdgeTimeRepository;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.route.repository.StationRouteEdge;
import com.ssafy.s15p21a104.domain.station.entity.Line;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** 역 여러 개의 소속 노선(ID·이름)을 쿼리 몇 번으로 묶어 오는 조회 헬퍼. 역 검색과 근처 역 조회가 같이 쓴다. */
@Component
@RequiredArgsConstructor
class StationLineLookup {

    private final RouteEdgeTimeRepository routeEdgeTimeRepository;
    private final RouteLineRepository routeLineRepository;

    /** 주어진 역 전체의 소속 노선을 쿼리 한 번으로 묶어 온다(역마다 따로 조회하는 N+1 방지). */
    Map<String, Set<String>> groupLineIdsByStation(Set<String> stationIds) {
        Map<String, Set<String>> result = new HashMap<>();
        for (StationRouteEdge edge : routeEdgeTimeRepository.findSubwayRouteEdgesTouchingStations(stationIds)) {
            if (stationIds.contains(edge.fromNode())) {
                result.computeIfAbsent(edge.fromNode(), key -> new TreeSet<>()).add(edge.routeId());
            }
            if (stationIds.contains(edge.toNode())) {
                result.computeIfAbsent(edge.toNode(), key -> new TreeSet<>()).add(edge.routeId());
            }
        }
        return result;
    }

    /** 등장한 노선 ID 전체의 이름을 쿼리 한 번으로 묶어 온다. */
    Map<String, String> lineNamesFor(Map<String, Set<String>> lineIdsByStation) {
        Set<String> allLineIds = lineIdsByStation.values().stream()
                .flatMap(Set::stream)
                .collect(Collectors.toSet());
        if (allLineIds.isEmpty()) {
            return Map.of();
        }
        return routeLineRepository.findAllById(allLineIds).stream()
                .collect(Collectors.toMap(Line::getLineId, Line::getName));
    }
}
