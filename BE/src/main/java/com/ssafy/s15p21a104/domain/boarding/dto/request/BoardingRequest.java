package com.ssafy.s15p21a104.domain.boarding.dto.request;

import com.ssafy.s15p21a104.domain.boarding.entity.BoardingStatus;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.time.OffsetDateTime;

/**
 * 탑승 확인 요청(S15P21A104-313, BE/docs/api/boarding-check-api-design.md 계약).
 *
 * @param mode 탑승 구간의 이동 수단
 * @param fromNodeId 승차 지점 ID
 * @param fromNodeName 승차 지점 이름 (선택)
 * @param toNodeId 하차 지점 ID
 * @param toNodeName 하차 지점 이름 (선택)
 * @param routeId 노선 ID (선택)
 * @param routeName 노선 이름 (선택)
 * @param status 탑승 확인 결과. FE "잘 모르겠어요" → UNKNOWN
 * @param departureTime 사용자가 고른 열차/버스 출발 시각 "HH:mm" (선택, status=UNKNOWN이면 보통 null)
 * @param reportedAt 클라이언트에서 이벤트가 발생한 시각 (필수)
 */
public record BoardingRequest(
        TravelMode mode,
        String fromNodeId,
        String fromNodeName,
        String toNodeId,
        String toNodeName,
        String routeId,
        String routeName,
        BoardingStatus status,
        String departureTime,
        OffsetDateTime reportedAt
) {
}
