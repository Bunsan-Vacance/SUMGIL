package com.ssafy.s15p21a104.load.crowd;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 지하철혼잡도정보의 역번호 → 우리 {@code station_id}.
 * <p>
 * 혼잡도 파일은 <b>노선별 역사코드</b>를 쓰고(시청 2호선 {@code 201} · 서울역 4호선 {@code 426}) 우리 station_id 는 그중
 * 최솟값이다({@code 151} · {@code 150}). 그래서 {@code conf/station-ids.csv} 의 {@code codes} 열
 * ("노선:코드;노선:코드")을 역방향으로 읽어 코드 → ID 표를 만든다. 앞 0 이 있는 표기와 없는 표기를 모두 키로 둔다.
 * <p>
 * 서울교통공사가 지선·순환 분기를 구분하려고 붙인 <b>가상 역번호</b>는 어느 노선 코드에도 없다
 * ({@code 9001 성수E} · {@code 9002 성수} · {@code 9003 신도림} · {@code 260 까치산} · {@code 9005 강동(마천)} ·
 * {@code 9006 응암S}). 이들은 {@code data/crowd/conf/crowd-station-aliases.csv} 로 실제 역에 잇는다.
 * <p>
 * 모르는 번호는 {@link Optional#empty()} 로 돌려주고 호출자가 경고로 집계한다 — 추측으로 채우지 않는다.
 */
public interface CrowdStationCodes {

    /** @return 혼잡도 역번호에 대응하는 station_id. 표에 없으면 비어 있다 */
    Optional<String> stationIdOf(String crowdCode);

    /**
     * @param idRows    conf/station-ids.csv 행 (station_id, name, codes, source)
     * @param aliasRows data/crowd/conf/crowd-station-aliases.csv 행 (혼잡도역번호, station_id, 역명, 근거)
     * @throws IllegalArgumentException 별칭이 역 ID 표에 없는 station_id 를 가리키면 (표가 어긋난 것)
     */
    static CrowdStationCodes from(List<Map<String, String>> idRows, List<Map<String, String>> aliasRows) {
        Map<String, String> byCode = new HashMap<>();
        java.util.Set<String> stationIds = new java.util.HashSet<>();
        for (Map<String, String> row : idRows) {
            String stationId = value(row, "station_id");
            if (stationId.isEmpty()) {
                continue;
            }
            stationIds.add(stationId);
            putBothForms(byCode, stationId, stationId);
            for (String part : value(row, "codes").split(";")) {
                String[] pair = part.split(":", 2);
                if (pair.length == 2) {
                    putBothForms(byCode, pair[1].trim(), stationId);
                }
            }
        }
        for (Map<String, String> row : aliasRows) {
            String crowdCode = value(row, "혼잡도역번호");
            String stationId = value(row, "station_id");
            if (crowdCode.isEmpty() || stationId.isEmpty()) {
                throw new IllegalArgumentException("혼잡도역번호 또는 station_id 가 빈 별칭 행: " + row);
            }
            if (!stationIds.contains(stationId)) {
                throw new IllegalArgumentException("별칭이 역 ID 표에 없는 역을 가리킨다: " + crowdCode + " → " + stationId);
            }
            putBothForms(byCode, crowdCode, stationId);   // 별칭이 노선 코드보다 우선한다
        }
        Map<String, String> table = Map.copyOf(byCode);
        return code -> code == null || code.isBlank() ? Optional.empty() : Optional.ofNullable(table.get(code.trim()));
    }

    /** 앞 0 이 있는 표기("0150")와 없는 표기("150")를 모두 키로 넣는다 — 원천마다 다르게 적는다. */
    private static void putBothForms(Map<String, String> table, String code, String stationId) {
        String trimmed = code.trim();
        if (trimmed.isEmpty()) {
            return;
        }
        table.put(trimmed, stationId);
        if (trimmed.chars().allMatch(Character::isDigit)) {
            table.put(String.valueOf(Long.parseLong(trimmed)), stationId);
        }
    }

    private static String value(Map<String, String> row, String column) {
        String v = row.get(column);
        return v == null ? "" : v.trim();
    }
}
