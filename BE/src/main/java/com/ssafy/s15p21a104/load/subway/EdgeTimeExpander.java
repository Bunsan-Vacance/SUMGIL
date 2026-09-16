package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * edge_time 은 (요일유형 0~2 × 30분 슬롯 0~47) 로 펼쳐진다.
 * 시각표에서 온 엣지는 슬롯별 기대 대기({@link SlotWaits})를 wait_sec 에 넣고, 시간대 정보가 없는 엣지(코레일 avg)는
 * 같은 travel_sec 을 복제하며 wait_sec 0 으로 둔다.
 */
public final class EdgeTimeExpander {

    static final int DOW_TYPES = SlotWaits.DOW_TYPES;
    static final int TIME_SLOTS = SlotWaits.SLOTS;

    private EdgeTimeExpander() {
    }

    public static List<EdgeTimeRow> expand(EdgeRow edge) {
        return expand(edge, null);
    }

    /** @param waits 이 엣지의 슬롯별 대기. null 이면 wait_sec 0 */
    public static List<EdgeTimeRow> expand(EdgeRow edge, SlotWaits waits) {
        List<EdgeTimeRow> rows = new ArrayList<>(DOW_TYPES * TIME_SLOTS);
        for (int dow = 0; dow < DOW_TYPES; dow++) {
            for (int slot = 0; slot < TIME_SLOTS; slot++) {
                int wait = waits == null ? 0 : waits.wait(dow, slot);
                rows.add(new EdgeTimeRow(edge.fromNode(), edge.toNode(), edge.mode(), edge.routeId(),
                        dow, slot, edge.travelSec(), wait, edge.source()));
            }
        }
        return rows;
    }

    public static List<EdgeTimeRow> expandAll(List<EdgeRow> edges) {
        return expandAll(edges, Map.of());
    }

    /** @param slotWaits 엣지 키("from|to|route") → 슬롯별 대기. 키가 없는 엣지는 wait_sec 0 */
    public static List<EdgeTimeRow> expandAll(List<EdgeRow> edges, Map<String, SlotWaits> slotWaits) {
        List<EdgeTimeRow> rows = new ArrayList<>(edges.size() * DOW_TYPES * TIME_SLOTS);
        for (EdgeRow edge : edges) {
            rows.addAll(expand(edge, slotWaits.get(edgeKey(edge))));
        }
        return rows;
    }

    public static String edgeKey(EdgeRow e) {
        return e.fromNode() + "|" + e.toNode() + "|" + e.routeId();
    }
}
