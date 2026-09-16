package com.ssafy.s15p21a104.load.subway;

/**
 * 노선별 역 좌표. 같은 물리 역이라도 노선마다 승강장 좌표가 조금 다르다.
 *
 * @param externalCode 원천의 역 코드 (서울교통공사 파일의 "고유역번호"). 실시간 API 매핑 참고용, 없으면 null
 */
public record StationCoord(String lineId, String stationName, double lat, double lng, String externalCode) {
}
