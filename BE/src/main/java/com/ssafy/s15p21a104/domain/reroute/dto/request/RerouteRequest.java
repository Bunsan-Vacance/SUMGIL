package com.ssafy.s15p21a104.domain.reroute.dto.request;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 잔여 경로 재탐색 요청(S15P21A104-193, FE 문서 §5.2 계약).
 *
 * @param step 원본 legs 인덱스 (0 이상)
 * @param boundaryId 현 경계 노드 ID (ID 또는 좌표 식별 — 여기서는 ID)
 * @param destStationId 목적지 역 ID (일반 장소면 null, destLat/destLng 사용)
 * @param destLat 목적지 위도 (일반 장소용, 선택)
 * @param destLng 목적지 경도 (일반 장소용, 선택)
 * @param modes 허용 수단 (선택)
 * @param priority fast/calm (선택, 기본 fast)
 * @param requestedAt 요청 시각 (필수)
 */
public record RerouteRequest(
        int step,
        String boundaryId,
        String destStationId,
        Double destLat,
        Double destLng,
        List<String> modes,
        String priority,
        OffsetDateTime requestedAt
) {
}
