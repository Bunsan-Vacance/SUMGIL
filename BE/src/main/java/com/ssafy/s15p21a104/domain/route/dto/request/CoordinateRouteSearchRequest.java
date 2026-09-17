package com.ssafy.s15p21a104.domain.route.dto.request;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 좌표 기반 통합 길찾기 요청(S15P21A104-185). 역뿐 아니라 카페·집·회사 등
 * 일반 장소를 출발·도착으로 받는다(FE-좌표기반-통합길찾기-API-협의요청.md 7절 제안 계약).
 *
 * @param origin 출발 장소 좌표
 * @param destination 도착 장소 좌표
 * @param modes 허용 수단(선택). 비우면 전체 허용 — 기존 역 ID 검색과 동일 규칙
 * @param priority 정렬 우선순위(선택)
 * @param departureTime 출발 시각(선택). 생략 시 현재 시각 기준
 */
public record CoordinateRouteSearchRequest(
        RoutePlaceRequest origin,
        RoutePlaceRequest destination,
        List<TravelMode> modes,
        RoutePriority priority,
        LocalDateTime departureTime
) {
}
