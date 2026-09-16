package com.ssafy.s15p21a104.domain.route.repository;

/** 역 검색(stations/search)에서 여러 역의 소속 노선을 한 번에 조회할 때 쓰는 JPQL 프로젝션. */
public record StationRouteEdge(String fromNode, String toNode, String routeId) {
}
