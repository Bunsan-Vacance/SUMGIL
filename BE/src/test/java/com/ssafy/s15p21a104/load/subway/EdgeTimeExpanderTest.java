package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** edge_time 은 (요일유형 3 × 30분 슬롯 48) 로 펼쳐진다. 시간대 정보가 없는 원천은 같은 값을 복제한다. */
class EdgeTimeExpanderTest {

    private final EdgeRow edge = new EdgeRow("서울", "시청", "SUBWAY", "1001", 120, "timetable");

    @Test
    @DisplayName("엣지 하나가 144 행이 된다")
    void expandsTo144Rows() {
        List<EdgeTimeRow> rows = EdgeTimeExpander.expand(edge);

        assertEquals(3 * 48, rows.size());
    }

    @Test
    @DisplayName("dow_type 0~2, time_slot 0~47 를 모두 한 번씩 덮는다")
    void coversAllDowAndSlots() {
        List<EdgeTimeRow> rows = EdgeTimeExpander.expand(edge);

        for (int dow = 0; dow < 3; dow++) {
            for (int slot = 0; slot < 48; slot++) {
                int d = dow;
                int s = slot;
                assertEquals(1, rows.stream().filter(r -> r.dowType() == d && r.timeSlot() == s).count());
            }
        }
    }

    @Test
    @DisplayName("이동 초·출처·노선은 그대로, 대기 초는 0")
    void copiesValues() {
        EdgeTimeRow r = EdgeTimeExpander.expand(edge).get(0);

        assertEquals("서울", r.fromNode());
        assertEquals("시청", r.toNode());
        assertEquals("SUBWAY", r.mode());
        assertEquals("1001", r.routeId());
        assertEquals(120, r.travelSec());
        assertEquals(0, r.waitSec());
        assertEquals("timetable", r.source());
    }

    @Test
    @DisplayName("여러 엣지를 한 번에 펼친다")
    void expandsAll() {
        EdgeRow other = new EdgeRow("시청", "서울", "SUBWAY", "1001", 120, "timetable");
        List<EdgeTimeRow> rows = EdgeTimeExpander.expandAll(List.of(edge, other));

        assertEquals(288, rows.size());
        assertTrue(rows.stream().anyMatch(r -> r.fromNode().equals("시청")));
    }
}
