package com.ssafy.s15p21a104.domain.route.finder;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;

/**
 * 응답 후보와 그 원본 엣지 목록({@link FoundPath})을 함께 들고 다닌다(S15P21A104-158).
 *
 * <p>혼잡도 스코어링(S-1)이 링크 단위·통과 시각 슬롯으로 바뀌면서, 이미 leg로 병합된
 * {@link RouteSearchResponse}만으로는 실제 지하철 링크(인접 역 구간)를 복원할 수 없다 —
 * 같은 노선을 여러 정거장 타면 leg 하나에 실제 링크 여러 개가 뭉쳐 있기 때문이다.
 * 그래서 {@link RouteCandidateFinder}가 응답으로 바꾸는 시점에 원본 {@link FoundPath}를
 * 버리지 않고 같이 넘긴다.
 */
public record ScoredCandidate(RouteSearchResponse response, FoundPath path) {
}
