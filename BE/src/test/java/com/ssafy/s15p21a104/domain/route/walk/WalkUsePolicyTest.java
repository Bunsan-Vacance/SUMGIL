package com.ssafy.s15p21a104.domain.route.walk;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** 연속 도보 상한(2026-09-27) — 끊김 없이 이어진 WALK 합만 센다. */
class WalkUsePolicyTest {

    private static Edge walk(int sec) {
        return new Edge("A", "B", WalkEdgeBuilder.WALK_ROUTE_ID, sec, 0, TravelMode.WALK);
    }

    @Test
    @DisplayName("W2: 연속 도보 합이 15분을 넘으면 거부, 탑승이 끼면 누적이 끊긴다")
    void w2_연속도보() {
        Edge subway = new Edge("B", "C", "L1", 600, 0, TravelMode.SUBWAY);

        assertTrue(WalkUsePolicy.allowedPath(List.of(walk(500), walk(400))));          // 900초 — 경계 허용
        assertFalse(WalkUsePolicy.allowedPath(List.of(walk(500), walk(401))));         // 901초
        assertTrue(WalkUsePolicy.allowedPath(List.of(walk(800), subway, walk(800))));  // 끊김 — 각각 800초
    }
}
