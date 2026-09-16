package com.ssafy.s15p21a104.load.subway;

import java.util.Arrays;
import java.util.Collection;
import java.util.List;

/**
 * 엣지 하나의 요일 3종 × 30분 슬롯 48개 기대 대기(초).
 * <p>
 * 정의: 슬롯 안 임의 시각에 승강장에 도착했을 때 다음 열차 출발까지의 기대 대기. 배차가 고르면 배차간격 ÷ 2 와 같고,
 * 열차가 없는 슬롯은 자연히 첫차까지의 대기가 된다. 막차 뒤는 같은 요일 유형의 첫차 + 24시간으로 이어 붙인다(근사, 문서화).
 * 출발 시각은 운행일 기준 초(자정 넘는 24:30 = 88,200)로 받고 24시간으로 접어 슬롯을 정한다.
 * 하루 운행이 없는 요일은 {@link #NO_SERVICE} 로 표시한다 — 값을 만들어 넣지 않기 위한 표식이다.
 */
public final class SlotWaits {

    public static final int DOW_TYPES = 3;
    public static final int SLOTS = 48;
    public static final int SLOT_SEC = 1800;
    public static final int DAY_SEC = 86400;
    /** 하루 운행이 없는 요일의 표식 (하루 이상 대기 = 사실상 운행 없음). */
    public static final int NO_SERVICE = DAY_SEC;

    private final int[][] waits;

    private SlotWaits(int[][] waits) {
        this.waits = waits;
    }

    /** 이미 계산된 3×48 표로 만든다. 값은 0~86,400 이어야 한다. */
    public static SlotWaits of(int[][] table) {
        if (table == null || table.length != DOW_TYPES) {
            throw new IllegalArgumentException("요일 3종 × 슬롯 48 표가 필요하다");
        }
        int[][] copy = new int[DOW_TYPES][];
        for (int d = 0; d < DOW_TYPES; d++) {
            if (table[d] == null || table[d].length != SLOTS) {
                throw new IllegalArgumentException("요일 " + d + " 의 슬롯 수가 48 이 아니다");
            }
            for (int w : table[d]) {
                if (w < 0 || w > DAY_SEC) {
                    throw new IllegalArgumentException("대기 초 범위 밖: " + w);
                }
            }
            copy[d] = table[d].clone();
        }
        return new SlotWaits(copy);
    }

    /** @param departuresByDow 요일 유형(0 평일, 1 토, 2 일·공휴일)별 출발 시각(운행일 기준 초) 목록 */
    public static SlotWaits fromDepartures(List<? extends Collection<Integer>> departuresByDow) {
        if (departuresByDow.size() != DOW_TYPES) {
            throw new IllegalArgumentException("요일 유형 3종의 출발 목록이 필요하다");
        }
        int[][] table = new int[DOW_TYPES][];
        for (int d = 0; d < DOW_TYPES; d++) {
            table[d] = expectedWaits(departuresByDow.get(d));
        }
        return new SlotWaits(table);
    }

    /**
     * 하루치 출발 시각으로 슬롯 48개의 기대 대기를 구한다.
     * 슬롯 [s, s+1800) 위에서 (다음 출발 − t) 를 적분해 1,800 으로 나눈다. 다음 출발이 슬롯 밖이면 그 시각까지,
     * 막차 뒤면 첫차 + 86,400 까지 잇는다. 출발이 하나도 없으면 전부 {@link #NO_SERVICE}.
     */
    public static int[] expectedWaits(Collection<Integer> departuresServiceDaySec) {
        int[] out = new int[SLOTS];
        if (departuresServiceDaySec.isEmpty()) {
            Arrays.fill(out, NO_SERVICE);
            return out;
        }
        int[] clock = departuresServiceDaySec.stream().mapToInt(SlotWaits::clockSeconds).sorted().toArray();
        for (int s = 0; s < SLOTS; s++) {
            int start = s * SLOT_SEC;
            int end = start + SLOT_SEC;
            int i = lowerBound(clock, start);
            double sum = 0;
            double a = start;
            while (a < end) {
                int next = i < clock.length ? clock[i] : clock[0] + DAY_SEC;
                double b = Math.min(end, next);
                sum += (b - a) * (next - (a + b) / 2.0);
                a = b;
                if (b == next) {
                    i++;
                }
            }
            out[s] = (int) Math.round(sum / SLOT_SEC);
        }
        return out;
    }

    public int wait(int dow, int slot) {
        return waits[dow][slot];
    }

    /** 운행일 기준 초 → 24시간으로 접은 시계 초 (88,200 → 1,800). */
    public static int clockSeconds(int serviceDaySec) {
        return Math.floorMod(serviceDaySec, DAY_SEC);
    }

    public static int slotOf(int serviceDaySec) {
        return clockSeconds(serviceDaySec) / SLOT_SEC;
    }

    private static int lowerBound(int[] sorted, int value) {
        int lo = 0;
        int hi = sorted.length;
        while (lo < hi) {
            int mid = (lo + hi) >>> 1;
            if (sorted[mid] < value) {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        return lo;
    }
}
