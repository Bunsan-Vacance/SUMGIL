package com.ssafy.s15p21a104.load.subway;

/**
 * 원천에서 읽은 인접 역 구간 (한 방향). 역명은 정규화된 값이다.
 *
 * @param source timetable(시간표 실측) | avg(거리 기반 추정)
 */
public record Segment(String lineId, String fromName, String toName, int travelSec, int distanceM, String source) {
}
