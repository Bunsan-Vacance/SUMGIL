package com.ssafy.s15p21a104.load.bike;

/**
 * bike_station 한 행. rental_id 는 bikeList 의 stationId(ST-xxx) 그대로 — API 명세의 rentalId·Redis 키 bike:stock:{rentalId} 와 같은 값.
 * name 은 원천 stationName 에서 대여소번호 접두어("102. ")를 뗀 것, dockCount 는 rackTotCnt (없으면 null).
 */
public record BikeStationRow(String rentalId, String name, Double lat, Double lng, Integer dockCount) {
}
