package com.ssafy.s15p21a104.domain.route.finder;

/**
 * 금지 엣지 키 — 출발·도착·노선 3값(S15P21A104-235).
 *
 * <p>Yen spur가 "이 엣지 하나만 빼고 탐색"할 때 쓴다. 그래프를 재조립하는 대신
 * 이 키 집합을 탐색기에 전달해 완화 시점에 건너뛴다.
 */
record EdgeKey(String fromNode, String toNode, String routeId) {
}
