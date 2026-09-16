package com.ssafy.s15p21a104.load.subway;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * 물리 역 ID 의 정본 — data/subway/conf/station-ids.csv (`station_id, name, codes, source`).
 * <p>
 * station_id 는 서울교통공사 역번호(노선별 역사코드 최솟값, 앞 0 제거 — 지하철혼잡도정보의 표기와 같다: 서울역 150). 코드가 없는
 * 코레일 전용 역은 9001부터 부여(source=assigned). codes 는 "노선:코드;노선:코드" 이고, assigned 행은 "노선:" 처럼 노선만 적는다.
 * 조회는 (정규화 역명, 노선) → codes 의 노선이 맞는 행, 없으면 이름이 표에 하나뿐일 때 그 행. 동명이역은 이름이 둘이라 노선으로만 갈린다.
 * 표에 없는 역은 비어 있고 호출자(빌더)가 적재를 멈춘다 — ID 가 몰래 생기지 않게. 개명은 name 만 바꾸고 ID 는 유지한다.
 */
public final class StationIdTable {

    private final Map<String, String> byNameAndLine = new HashMap<>();
    private final Map<String, List<String>> byName = new HashMap<>();
    private final Set<String> ids = new LinkedHashSet<>();
    private final boolean identity;

    private StationIdTable(boolean identity) {
        this.identity = identity;
    }

    public static StationIdTable from(List<Map<String, String>> rows) {
        StationIdTable table = new StationIdTable(false);
        for (Map<String, String> row : rows) {
            String id = value(row, "station_id");
            String name = value(row, "name");
            if (id.isEmpty() || name.isEmpty()) {
                throw new IllegalArgumentException("station_id 또는 name 이 빈 행: " + row);
            }
            if (!table.ids.add(id)) {
                throw new IllegalArgumentException("station_id 가 겹침: " + id);
            }
            for (String part : value(row, "codes").split(";")) {
                String line = part.split(":", 2)[0].trim();
                if (line.isEmpty()) {
                    continue;
                }
                String previous = table.byNameAndLine.put(name + "|" + line, id);
                if (previous != null && !previous.equals(id)) {
                    throw new IllegalArgumentException("같은 (역명, 노선)에 ID 둘: " + name + " " + line + " → " + previous + ", " + id);
                }
            }
            List<String> sameName = table.byName.computeIfAbsent(name, k -> new ArrayList<>());
            if (!sameName.contains(id)) {
                sameName.add(id);
            }
        }
        return table;
    }

    /** ID = 역명. 69 까지의 규칙과 같은 동작으로 테스트 픽스처 전용이다 — 운영 적재에는 쓰지 않는다. */
    public static StationIdTable identity() {
        return new StationIdTable(true);
    }

    public Optional<String> idOf(String name, String lineId) {
        if (identity) {
            return Optional.of(name);
        }
        String exact = byNameAndLine.get(name + "|" + lineId);
        if (exact != null) {
            return Optional.of(exact);
        }
        List<String> candidates = byName.get(name);
        return candidates != null && candidates.size() == 1 ? Optional.of(candidates.get(0)) : Optional.empty();
    }

    public int size() {
        return ids.size();
    }

    public Set<String> ids() {
        return Set.copyOf(ids);
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }
}
