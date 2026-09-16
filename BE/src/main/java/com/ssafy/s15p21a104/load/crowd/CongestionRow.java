package com.ssafy.s15p21a104.load.crowd;

import java.math.BigDecimal;

/**
 * congestion 한 행.
 *
 * @param targetType STATION | LINE (ROUTE 는 경로 개념이라 의미가 정해지지 않아 만들지 않는다)
 * @param targetId   STATION 이면 station_id, LINE 이면 line_id
 * @param level      혼잡도 %. 정원 대비라 <b>100 을 넘을 수 있다</b> (원천 최대 144.6)
 * @param source     stat(통계) | live(실시간). 이 로더는 stat
 */
public record CongestionRow(String targetType, String targetId, int dowType, int timeSlot,
                            BigDecimal level, String source) {
}
