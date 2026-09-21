package com.ssafy.s15p21a104.domain.route.finder.raptor;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 연결망 접근·이탈 closure 단위 테스트(5부 R-A1) — RAPTOR 경계가 다중 홉(대여소 체인)을
 * 비용 + 경로 사슬 테이블로 공급하기 위한 one-to-many Dijkstra.
 */
class RaptorAccessClosureTest {

    private static final List<RaptorFinder.Connection> CHAIN = List.of(
            new RaptorFinder.Connection("PLACE-ORIGIN", "R1", 60, TravelMode.WALK),
            new RaptorFinder.Connection("R1", "R2", 120, TravelMode.BIKE),
            new RaptorFinder.Connection("R2", "S", 120, TravelMode.BIKE));

    @Test
    @DisplayName("A1: 출발 정방향 — 대여소 체인 다중 홉 비용과 사슬을 만든다")
    void a1_정방향체인() {
        Map<String, RaptorFinder.Access> access = RaptorAccessClosure.from("PLACE-ORIGIN", CHAIN);

        assertEquals(0, access.get("PLACE-ORIGIN").costSec());
        assertNull(access.get("PLACE-ORIGIN").fromNode());
        assertEquals(60, access.get("R1").costSec());
        assertEquals("PLACE-ORIGIN", access.get("R1").fromNode());
        assertEquals(180, access.get("R2").costSec());
        assertEquals("R1", access.get("R2").fromNode());
        assertEquals(TravelMode.BIKE, access.get("R2").mode());
        assertEquals(300, access.get("S").costSec());
        assertEquals(120, access.get("S").legSec());
    }

    @Test
    @DisplayName("A2: 도착 역방향 — 체인을 되짚어 비용과 다음 구간을 만든다")
    void a2_역방향체인() {
        List<RaptorFinder.Connection> toDest = List.of(
                new RaptorFinder.Connection("S", "R2", 120, TravelMode.BIKE),
                new RaptorFinder.Connection("R2", "R1", 120, TravelMode.BIKE),
                new RaptorFinder.Connection("R1", "PLACE-DEST", 60, TravelMode.WALK));

        Map<String, RaptorFinder.Egress> egress = RaptorAccessClosure.to("PLACE-DEST", toDest);

        assertEquals(0, egress.get("PLACE-DEST").costSec());
        assertNull(egress.get("PLACE-DEST").toNode());
        assertEquals(300, egress.get("S").costSec());
        assertEquals("R2", egress.get("S").toNode());
        assertEquals(TravelMode.BIKE, egress.get("S").mode());
        assertEquals(180, egress.get("R2").costSec());
        assertEquals("R1", egress.get("R2").toNode());
    }

    @Test
    @DisplayName("A3: 최소 비용 경로가 이긴다 — 긴 우회는 채택되지 않는다")
    void a3_최소비용() {
        List<RaptorFinder.Connection> connections = List.of(
                new RaptorFinder.Connection("O", "X", 100, TravelMode.WALK),
                new RaptorFinder.Connection("O", "Y", 50, TravelMode.WALK),
                new RaptorFinder.Connection("Y", "X", 40, TravelMode.WALK));

        Map<String, RaptorFinder.Access> access = RaptorAccessClosure.from("O", connections);

        assertEquals(90, access.get("X").costSec());
        assertEquals("Y", access.get("X").fromNode());
    }

    @Test
    @DisplayName("A4: 도달 불가 정점은 결과에 없다")
    void a4_도달불가() {
        Map<String, RaptorFinder.Access> access = RaptorAccessClosure.from("PLACE-ORIGIN", CHAIN);

        assertFalse(access.containsKey("고립된섬"));
    }
}
