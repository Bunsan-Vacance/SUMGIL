package com.ssafy.s15p21a104.load.subway;

/** line 테이블 1행. line_id 는 서울시 실시간 지하철 API 의 subwayId 다. */
public record LineRow(String lineId, String name) {
}
