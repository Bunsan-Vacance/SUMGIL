package com.ssafy.s15p21a104.domain.route.dto.request;

/**
 * 좌표 기반 경로 검색의 장소 하나(출발 또는 도착). 역 ID 없이 WGS84 위경도로만 표현한다.
 *
 * @param lat 위도(WGS84). 필수
 * @param lng 경도(WGS84). 필수
 * @param name 표시용 이름(선택). 응답에는 쓰지 않으며 FE가 자체 보유 이름을 표시에 사용한다.
 */
public record RoutePlaceRequest(Double lat, Double lng, String name) {
}
