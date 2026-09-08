package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.List;

/**
 * edge_time 은 (요일유형 0~2 × 30분 슬롯 0~47) 로 펼쳐진다.
 * 시간대별 값이 없는 원천은 같은 값을 복제한다. 시간대별 데이터가 생기면 해당 슬롯만 덮어쓴다.
 */
public final class EdgeTimeExpander {

    static final int DOW_TYPES = 3;
    static final int TIME_SLOTS = 48;

    private EdgeTimeExpander() {
    }

    public static List<EdgeTimeRow> expand(EdgeRow edge) {
        List<EdgeTimeRow> rows = new ArrayList<>(DOW_TYPES * TIME_SLOTS);
        for (int dow = 0; dow < DOW_TYPES; dow++) {
            for (int slot = 0; slot < TIME_SLOTS; slot++) {
                rows.add(new EdgeTimeRow(edge.fromNode(), edge.toNode(), edge.mode(), edge.routeId(),
                        dow, slot, edge.travelSec(), 0, edge.source()));
            }
        }
        return rows;
    }

    public static List<EdgeTimeRow> expandAll(List<EdgeRow> edges) {
        List<EdgeTimeRow> rows = new ArrayList<>(edges.size() * DOW_TYPES * TIME_SLOTS);
        for (EdgeRow edge : edges) {
            rows.addAll(expand(edge));
        }
        return rows;
    }
}
