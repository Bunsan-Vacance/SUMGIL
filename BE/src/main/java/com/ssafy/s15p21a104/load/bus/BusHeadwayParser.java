package com.ssafy.s15p21a104.load.bus;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 배차간격 수집 CSV(`data/bus/seoul-bus-headway_<날짜>.csv`) → {@link BusHeadwayRow}.
 * 열은 {@code busRouteId · rtNm · term · firstTm · lastTm · routeType · observedStId · mkTm} 8개이고
 * 이 로더는 {@code busRouteId}·{@code term} 만 쓴다.
 * <p>
 * <b>첫차·막차는 읽지 않는다.</b> 열은 있지만 적재하지 않는다 — 2026-09-08 과 09-17 두 관측에서
 * {@code term} 은 14개 노선 전부 같았는데 첫차·막차는 12개가 몇 분씩 달라졌다. 운행 기록을 반영해 갱신되는 값이라
 * 정적 표에 넣으면 그날부터 낡는다. 나중에 쓰기로 하면 재수집 없이 이 CSV 에서 꺼낼 수 있다.
 * <p>
 * 원천은 도착정보(공공데이터포털 15000314)이고 수집은 {@code BE/scripts/data/bus-headway-fetch.mjs} 가 한다.
 * 이 파서는 API 를 부르지 않는다.
 */
public final class BusHeadwayParser {

    /** 없으면 수집 스크립트가 바뀐 것이라 멈춘다. 나머지 열은 참고용이라 없어도 읽는다. */
    private static final List<String> REQUIRED_COLUMNS = List.of("busRouteId", "term");
    private static final int EXAMPLE_LIMIT = 10;

    /**
     * @param sourceRows  읽은 원천 행 수
     * @param withHeadway 배차간격이 있는 노선 수 (0·빈 칸은 세지 않는다)
     * @param skipped     노선 ID 가 없거나 term 이 숫자가 아니어서 행을 만들지 않은 수
     */
    public record Stats(int sourceRows, int withHeadway, int skipped) {
    }

    public record Result(List<BusHeadwayRow> rows, Stats stats) {
    }

    private final List<String> warnings = new ArrayList<>();

    public Result parse(List<Map<String, String>> sourceRows) {
        warnings.clear();
        List<BusHeadwayRow> rows = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        List<String> skippedExamples = new ArrayList<>();
        int skipped = 0;
        int withHeadway = 0;
        boolean columnsChecked = false;

        for (Map<String, String> row : sourceRows) {
            if (!columnsChecked) {
                requireColumns(row);
                columnsChecked = true;
            }
            String routeId = value(row, "busRouteId");
            if (routeId.isEmpty()) {
                skipped++;
                if (skippedExamples.size() < EXAMPLE_LIMIT) {
                    skippedExamples.add("(노선 ID 없음)");
                }
                continue;
            }
            // 수집 스크립트가 이미 노선당 한 행으로 합치므로 중복은 드물다. 나면 먼저 본 것을 남긴다.
            if (!seen.add(routeId)) {
                continue;
            }
            String term = value(row, "term");
            Integer headway;
            if (term.isEmpty()) {
                headway = null;
            } else {
                try {
                    int parsed = Integer.parseInt(term);
                    // 0 은 "배차 0분" 이 아니라 그 시각에 운행 중이 아니라는 뜻이다 — 값을 만들어 넣지 않는다.
                    headway = parsed == 0 ? null : parsed;
                } catch (NumberFormatException e) {
                    skipped++;
                    seen.remove(routeId);
                    if (skippedExamples.size() < EXAMPLE_LIMIT) {
                        skippedExamples.add(routeId + "(term '" + term + "')");
                    }
                    continue;
                }
            }
            if (headway != null && headway > 0) {
                withHeadway++;
            }
            rows.add(new BusHeadwayRow(routeId, headway));
        }

        if (skipped > 0) {
            warnings.add("노선 ID 가 없거나 배차간격이 숫자가 아니어서 " + skipped + "행 건너뜀: " + head(skippedExamples));
        }
        return new Result(List.copyOf(rows), new Stats(sourceRows.size(), withHeadway, skipped));
    }

    public List<String> warnings() {
        return List.copyOf(warnings);
    }

    private static void requireColumns(Map<String, String> row) {
        List<String> missing = REQUIRED_COLUMNS.stream().filter(c -> !row.containsKey(c)).toList();
        if (!missing.isEmpty()) {
            throw new IllegalStateException("배차간격 CSV 에 필수 열이 없습니다: " + String.join(", ", missing)
                    + " (있는 열: " + String.join(", ", row.keySet()) + ")");
        }
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }

    private static String head(List<String> items) {
        String joined = String.join(", ", items);
        return items.size() >= EXAMPLE_LIMIT ? joined + ", …" : joined;
    }
}
