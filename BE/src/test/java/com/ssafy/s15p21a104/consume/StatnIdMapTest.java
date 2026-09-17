package com.ssafy.s15p21a104.consume;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 실시간 도착 API 의 statnId → 우리 station_id 대응표 (S15P21A104-171).
 * 표 자체는 {@code BE/scripts/data/statn-id-map-build.mjs} 가 prod Kafka 덤프로 만든다 — 생성 규칙 테스트는 그쪽에 있다.
 * 여기서는 "만들어진 표를 제대로 읽어 찾아주는가"만 본다.
 */
class StatnIdMapTest {

    @Test
    @DisplayName("statnId 로 우리 station_id 를 찾는다")
    void 찾는다() {
        StatnIdMap map = StatnIdMap.parse("""
                statn_id,station_id,line_id,name
                1002000222,222,1002,역삼
                1001000133,150,1001,서울
                """);

        assertEquals(Optional.of("222"), map.stationId("1002000222"));
        assertEquals(Optional.of("150"), map.stationId("1001000133"));
        assertEquals(2, map.size());
    }

    @Test
    @DisplayName("표에 없으면 비어 있다 — 없는 역을 엉뚱한 곳에 쓰지 않는다")
    void 없으면_빈값() {
        StatnIdMap map = StatnIdMap.parse("""
                statn_id,station_id,line_id,name
                1002000222,222,1002,역삼
                """);

        assertEquals(Optional.empty(), map.stationId("1032000351"), "GTX-A 는 표에 없다");
        assertEquals(Optional.empty(), map.stationId(null));
        assertEquals(Optional.empty(), map.stationId(""));
    }

    @Test
    @DisplayName("커밋된 정본 표를 클래스패스에서 읽는다")
    void 정본_표를_읽는다() {
        StatnIdMap map = StatnIdMap.fromClasspath();

        assertTrue(map.size() > 600, "정본 표가 비었거나 못 읽었다 — 실제 %d행".formatted(map.size()));
        // 1호선은 statnId 체계가 우리와 다르다. 이름·노선으로 붙였으므로 여기서 찾아져야 한다.
        assertEquals(Optional.of("150"), map.stationId("1001000133"), "서울역");
        // 동명이역은 노선으로 갈렸다 — 둘이 다른 station_id 여야 한다.
        assertEquals(Optional.of("240"), map.stationId("1002000240"), "신촌 2호선");
        assertEquals(Optional.of("1252"), map.stationId("1063080312"), "신촌 경의중앙선");
        // 괄호 부역명이 붙어 오던 역
        assertEquals(Optional.of("432"), map.stationId("1004000432"), "총신대입구(이수)");
    }
}
