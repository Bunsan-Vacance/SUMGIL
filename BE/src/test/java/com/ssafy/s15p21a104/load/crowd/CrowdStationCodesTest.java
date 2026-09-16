package com.ssafy.s15p21a104.load.crowd;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 지하철혼잡도정보의 역번호 → 우리 station_id.
 * 혼잡도는 노선별 역사코드(시청 2호선 201 · 서울역 4호선 426)를 쓰고 우리 station_id 는 그중 최솟값(151 · 150)이라
 * conf/station-ids.csv 의 codes 열을 역방향으로 읽는다. 서울교통공사가 지선·순환 분기용으로 붙인 가상 역번호
 * (9001 성수E · 9003 신도림 · 260 까치산 등 6건)는 별칭 표로 실제 역에 잇는다.
 */
class CrowdStationCodesTest {

    private static Map<String, String> id(String stationId, String name, String codes) {
        return Map.of("station_id", stationId, "name", name, "codes", codes, "source", "timetable");
    }

    private static Map<String, String> alias(String crowdCode, String stationId, String name) {
        return Map.of("혼잡도역번호", crowdCode, "station_id", stationId, "역명", name, "근거", "테스트");
    }

    private final List<Map<String, String>> idRows = List.of(
            id("150", "서울", "1001:0150;1004:0426"),
            id("151", "시청", "1001:0151;1002:0201"),
            id("211", "성수", "1002:0211"),
            id("200", "까치산", "1002:0200;1005:2519"));

    @Test
    @DisplayName("codes 의 노선별 코드로 station_id 를 찾는다 — 시청 2호선 201 → 151, 서울역 4호선 426 → 150. 앞 0 이 있어도 없어도 같다")
    void resolvesByLineCode() {
        CrowdStationCodes codes = CrowdStationCodes.from(idRows, List.of());

        assertEquals(Optional.of("151"), codes.stationIdOf("201"));
        assertEquals(Optional.of("150"), codes.stationIdOf("426"));
        assertEquals(Optional.of("150"), codes.stationIdOf("0150"));
        assertEquals(Optional.of("211"), codes.stationIdOf("211"));
    }

    @Test
    @DisplayName("station_id 자체도 키다 — 혼잡도가 최솟값을 쓰는 역(서울역 1호선 150)은 그대로 맞는다")
    void stationIdItselfIsAKey() {
        CrowdStationCodes codes = CrowdStationCodes.from(idRows, List.of());

        assertEquals(Optional.of("150"), codes.stationIdOf("150"));
    }

    @Test
    @DisplayName("별칭 표가 우선한다 — 가상 역번호 9001 성수E → 211, 260 까치산 → 200 (2호선 신정지선 코드)")
    void aliasWins() {
        CrowdStationCodes codes = CrowdStationCodes.from(idRows,
                List.of(alias("9001", "211", "성수E"), alias("260", "200", "까치산")));

        assertEquals(Optional.of("211"), codes.stationIdOf("9001"));
        assertEquals(Optional.of("200"), codes.stationIdOf("260"));
    }

    @Test
    @DisplayName("모르는 역번호는 비어 있다 — 호출자가 경고로 집계하고 값을 만들어 넣지 않는다")
    void unknownIsEmpty() {
        CrowdStationCodes codes = CrowdStationCodes.from(idRows, List.of());

        assertTrue(codes.stationIdOf("9999").isEmpty());
        assertTrue(codes.stationIdOf("").isEmpty());
        assertTrue(codes.stationIdOf(null).isEmpty());
    }

    @Test
    @DisplayName("별칭이 역 ID 표에 없는 station_id 를 가리키면 표가 잘못된 것이다 — 만들 때 멈춘다")
    void aliasToUnknownStationFails() {
        assertThrows(IllegalArgumentException.class,
                () -> CrowdStationCodes.from(idRows, List.of(alias("9001", "9999", "없는역"))));
    }
}
