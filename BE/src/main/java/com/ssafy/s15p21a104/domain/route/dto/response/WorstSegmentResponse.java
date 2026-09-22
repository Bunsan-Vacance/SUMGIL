package com.ssafy.s15p21a104.domain.route.dto.response;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;

/**
 * 경로에서 가장 혼잡한 구간(2026-09-22, FE-BE 통합 계약 §2 확장).
 *
 * <p>표시용 위치 정보다. 값이 있는 경로({@code dataStatus=AVAILABLE})에서만 채워지고,
 * 없으면 {@code null}이다 — 결측을 빈 문자열 같은 것으로 채우지 않는다.
 *
 * @param mode 이 구간의 수단(SUBWAY·BUS)
 * @param fromNodeId 구간 시작 노드 ID
 * @param fromNodeName 구간 시작 표시명
 * @param toNodeId 구간 끝 노드 ID
 * @param toNodeName 구간 끝 표시명
 * @param congestionPercent 이 구간의 혼잡도(%, 정원 대비·공통 축)
 */
public record WorstSegmentResponse(
        TravelMode mode,
        String fromNodeId,
        String fromNodeName,
        String toNodeId,
        String toNodeName,
        Double congestionPercent
) {
}
