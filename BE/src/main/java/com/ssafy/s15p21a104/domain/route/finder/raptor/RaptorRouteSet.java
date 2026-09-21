package com.ssafy.s15p21a104.domain.route.finder.raptor;

import java.util.List;

/**
 * RAPTOR 탐색 입력 묶음(S15P21A104-217 ③) — 슬롯별 노선·연결.
 *
 * @param routes 노선(버스·지하철) 순서 배열
 * @param connections 노선 밖 연결(도보·자전거, 요청별 접근 엣지 포함 가능)
 */
public record RaptorRouteSet(List<RaptorFinder.Route> routes,
                             List<RaptorFinder.Connection> connections) {
}
