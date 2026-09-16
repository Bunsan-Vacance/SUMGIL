package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * conf/station-ids.csv — 물리 역 ID 의 정본. station_id 는 서울교통공사 역번호(노선별 코드 최솟값, 앞 0 제거),
 * 코드가 없는 코레일 전용 역은 9001부터 부여. 로더는 (정규화 역명, 노선) → station_id 를 이 표로만 정하고, 표에 없는 역은 적재를 멈춘다.
 */
class StationIdTableTest {

    private static Map<String, String> row(String id, String name, String codes, String source) {
        return Map.of("station_id", id, "name", name, "codes", codes, "source", source);
    }

    // codes = "노선:코드;…". 코드가 없는 역(assigned)은 "노선:" 처럼 노선만 적어 어느 노선의 역인지 남긴다.
    private final StationIdTable table = StationIdTable.from(List.of(
            row("150", "서울", "1001:0150;1004:0426", "timetable"),
            row("240", "신촌", "1002:0240", "timetable"),
            row("9002", "신촌", "1063:", "assigned"),
            row("9001", "가천대", "1075:", "assigned")));

    @Test
    @DisplayName("(역명, 노선) 이 codes 에 있으면 그 행의 ID — 서울 1호선·4호선 둘 다 150")
    void resolvesByNameAndLine() {
        assertEquals(Optional.of("150"), table.idOf("서울", "1001"));
        assertEquals(Optional.of("150"), table.idOf("서울", "1004"));
    }

    @Test
    @DisplayName("노선이 codes 에 없어도 이름이 표에 하나뿐이면 그 ID — 새 노선이 들어온 환승역(서울에 경의중앙이 붙는 경우)")
    void fallsBackToUniqueName() {
        assertEquals(Optional.of("9001"), table.idOf("가천대", "1075"));
        assertEquals("150", table.idOf("서울", "1063").orElseThrow());
    }

    @Test
    @DisplayName("동명이역: 같은 이름의 행이 둘이면 (역명, 노선) 으로만 갈라진다 — 신촌(2호선) 240, 신촌(경의중앙) 9002, 모르는 노선은 비어 있음")
    void disambiguatesSameNames() {
        assertEquals(Optional.of("240"), table.idOf("신촌", "1002"));
        assertEquals(Optional.of("9002"), table.idOf("신촌", "1063"));
        assertTrue(table.idOf("신촌", "1094").isEmpty());
    }

    @Test
    @DisplayName("표에 없는 역은 비어 있다 — 호출자가 적재를 멈춘다")
    void unknownIsEmpty() {
        assertTrue(table.idOf("없는역", "1001").isEmpty());
    }

    @Test
    @DisplayName("ID 가 겹치거나 비어 있는 표는 만들 수 없다")
    void rejectsDuplicateOrBlankIds() {
        assertThrows(IllegalArgumentException.class, () -> StationIdTable.from(List.of(
                row("150", "서울", "", "timetable"), row("150", "시청", "", "timetable"))));
        assertThrows(IllegalArgumentException.class, () -> StationIdTable.from(List.of(row("", "서울", "", "timetable"))));
    }

    @Test
    @DisplayName("identity(): ID = 역명. 옛 규칙과 같은 동작으로, 테스트 픽스처 전용이다")
    void identityMapsNameToItself() {
        assertEquals(Optional.of("왕십리"), StationIdTable.identity().idOf("왕십리", "1002"));
    }

    @Test
    @DisplayName("표 크기와 전체 ID 목록을 돌려준다")
    void exposesSize() {
        assertEquals(4, table.size());
        assertTrue(table.ids().contains("9001"));
    }
}
