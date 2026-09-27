package com.ssafy.s15p21a104.domain.route.walk;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import java.util.Objects;

/**
 * 도보 사용 규칙(2026-09-27 사용자 결정) — 순수 로직, 한 곳 정의.
 *
 * <p>연속 도보(끊김 없이 이어진 WALK 엣지 합)는 {@value #MAX_WALK_RUN_SEC}초(15분, 약 1km)까지만
 * 허용한다. 접근 closure가 역↔대여소↔정류장 도보 연결을 이어 붙여 "한티→문정 114분 도보" 같은
 * 경로를 만들던 것을 막는다. 자전거·탑승·환승이 끼면 누적이 끊긴다.
 */
public final class WalkUsePolicy {

    /** 연속 도보 상한(초). */
    public static final int MAX_WALK_RUN_SEC = 15 * 60;

    private WalkUsePolicy() {
    }

    /**
     * @param walkRunSec 이어온 연속 도보(초)
     * @param addSec 추가할 도보 연결(초)
     * @return 상한 안이면 true
     */
    public static boolean allowsWalk(int walkRunSec, int addSec) {
        return walkRunSec + addSec <= MAX_WALK_RUN_SEC;
    }

    /**
     * 경로 엣지 열이 연속 도보 상한을 지키는가(엔진 공통 안전망 — 레거시 폴백 포함).
     *
     * @param edges 경로 엣지(순서대로)
     * @return 규칙 준수 여부
     */
    public static boolean allowedPath(List<Edge> edges) {
        Objects.requireNonNull(edges, "edges");
        int run = 0;
        for (Edge edge : edges) {
            if (edge.mode() != TravelMode.WALK) {
                run = 0;
                continue;
            }
            run += edge.travelSec();
            if (run > MAX_WALK_RUN_SEC) {
                return false;
            }
        }
        return true;
    }
}
