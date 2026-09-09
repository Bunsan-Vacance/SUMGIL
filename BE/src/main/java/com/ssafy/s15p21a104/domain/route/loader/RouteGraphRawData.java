package com.ssafy.s15p21a104.domain.route.loader;

import java.util.List;
import java.util.Map;

/**
 * 그래프 조립에 쓰는 원시 데이터 묶음.
 *
 * <p>{@link RouteGraphLoader}의 입력이며, 실제 조회(DB 접근)와 분리하기 위해
 * DB 조회 계약(Repository)이 만든 값들을 그대로 넘겨준다. 그래프 조립 로직은
 * DB·Redis 없이 단위 테스트할 수 있다.
 *
 * @param subwayEdges SUBWAY 구간 행(대표 슬롯 필터 후)
 * @param stationNames 역 ID별 역 이름
 * @param lineNames 노선 ID별 노선 이름
 */
public record RouteGraphRawData(
        List<RouteEdgeRow> subwayEdges,
        Map<String, String> stationNames,
        Map<String, String> lineNames
) {
}
