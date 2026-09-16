package com.ssafy.s15p21a104.load.subway;

/**
 * 시각표에서 온 방향 있는 인접 역 구간. 역명은 정규화된 값이다.
 * {@link Segment}(무방향, 빌더가 양방향 엣지 생성)와 달리 이 방향의 엣지 하나만 만든다 — 2호선 순환·6호선 응암순환처럼
 * 실제 운행 방향만 그래프에 남기기 위해서다. 반대 방향은 반대 방향 열차가 있어야 생긴다.
 *
 * @param source timetable(시각표 실측)
 */
public record DirectedSegment(String lineId, String fromName, String toName, int travelSec, String source) {
}
