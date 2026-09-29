package com.ssafy.s15p21a104.domain.congestion.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-158(통지 05 S-1): 방향 판정. 실측 혼잡도 CSV로 정정됨
 * (이원빈 회신 `TO_ROUTE-subway-direction-01.md`, 2026-09-21).
 */
class SubwayDirectionResolverTest {

    @Test
    @DisplayName("1호선은 역번호 오름차순이면 상선")
    void 일호선_오름차순_상선() {
        assertEquals(Optional.of("상선"), SubwayDirectionResolver.resolve("221", "222", "1001"));
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("222", "221", "1001"));
    }

    @Test
    @DisplayName("2호선 본선은 오름차순이면 내선, 내림차순이면 외선")
    void 이호선_본선_내선_외선() {
        assertEquals(Optional.of("내선"), SubwayDirectionResolver.resolve("221", "222", "1002"));
        assertEquals(Optional.of("외선"), SubwayDirectionResolver.resolve("222", "221", "1002"));
    }

    @Test
    @DisplayName("3~8호선은 역번호 오름차순이면 하선(1호선과 반대)")
    void 삼호선에서_팔호선_오름차순_하선() {
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("309", "310", "1003"));
        assertEquals(Optional.of("상선"), SubwayDirectionResolver.resolve("310", "309", "1003"));
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("2511", "2512", "1005"));
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("2810", "2811", "1008"));
    }

    @Test
    @DisplayName("2호선 지선 내부 링크는 더 이상 통째로 결측 처리되지 않는다(이전 버그 수정)")
    void 지선_내부_링크는_정상_판정() {
        // 성수지선: 성수(211) → 용답(244), 둘 다 지선 역이지만 반전 링크는 아니다.
        assertEquals(Optional.of("내선"), SubwayDirectionResolver.resolve("211", "244", "1002"));
        // 신정지선: 신도림(234) → 도림천(247).
        assertEquals(Optional.of("내선"), SubwayDirectionResolver.resolve("234", "247", "1002"));
    }

    @Test
    @DisplayName("2호선 본선 구간(문래 포함)은 지선으로 오인돼 결측 처리되지 않는다(이전 버그 수정)")
    void 문래가_낀_본선_구간도_정상_판정() {
        assertEquals(Optional.of("내선"), SubwayDirectionResolver.resolve("234", "235", "1002"));
    }

    @Test
    @DisplayName("용두↔신설동(2호선 성수지선 경계)은 반전 링크라 판정을 보류한다")
    void 용두_신설동_경계_보류() {
        assertTrue(SubwayDirectionResolver.resolve("250", "156", "1002").isEmpty());
        assertTrue(SubwayDirectionResolver.resolve("156", "250", "1002").isEmpty());
    }

    @Test
    @DisplayName("신정네거리↔까치산(2호선 신정지선 경계)은 반전 링크라 판정을 보류한다")
    void 신정네거리_까치산_경계_보류() {
        assertTrue(SubwayDirectionResolver.resolve("249", "200", "1002").isEmpty());
        assertTrue(SubwayDirectionResolver.resolve("200", "249", "1002").isEmpty());
    }

    @Test
    @DisplayName("동묘앞↔신설동(1호선, 나중 개통역)은 반전 링크라 판정을 보류한다")
    void 동묘앞_신설동_경계_보류() {
        assertTrue(SubwayDirectionResolver.resolve("159", "156", "1001").isEmpty());
        assertTrue(SubwayDirectionResolver.resolve("156", "159", "1001").isEmpty());
    }

    @Test
    @DisplayName("역번호가 숫자가 아니면(수도권 확장 역 등) 판정을 보류한다")
    void 숫자아닌_역번호_보류() {
        assertTrue(SubwayDirectionResolver.resolve("D004", "A01", "1113").isEmpty());
    }

    @Test
    @DisplayName("환승역이 다른 노선의 작은 번호를 ID로 써도(교대=223) 그 노선의 역번호로 방향을 판정한다")
    void 환승역_노선별_역번호() {
        // 3호선: 고속터미널 0329 → 교대 0330 → 남부터미널 0331. 교대 station_id는 2호선 번호 223.
        assertEquals(Optional.of("상선"), SubwayDirectionResolver.resolve("223", "329", "1003")); // 교대→고속터미널
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("329", "223", "1003")); // 고속터미널→교대
        assertEquals(Optional.of("하선"), SubwayDirectionResolver.resolve("223", "331", "1003")); // 교대→남부터미널
    }

    @Test
    @DisplayName("3~8호선 인접 구간 전수 — 노선 순서(역 좌표 CSV)대로 가면 모두 하선, 거꾸로 가면 모두 상선")
    void 인접구간_전수() throws Exception {
        java.util.Map<String, String> renamed = java.util.Map.of("당고개", "불암산", "뚝섬유원지", "자양");
        // 역 좌표 CSV의 역번호는 station-ids.csv와 어긋나는 곳이 있어(6호선 화랑대·봉화산) 노선+역명으로 잇는다.
        java.util.Map<String, String> sidByLineName = new java.util.HashMap<>();
        try (var in = getClass().getClassLoader().getResourceAsStream("data/subway/conf/station-ids.csv");
             var reader = new java.io.BufferedReader(new java.io.InputStreamReader(in, java.nio.charset.StandardCharsets.UTF_8))) {
            reader.readLine();
            for (String line; (line = reader.readLine()) != null; ) {
                String[] cells = line.split(",", -1);
                for (String code : cells[2].split(";")) {
                    sidByLineName.put(code.split(":")[0] + ":" + cells[1], cells[0]);
                }
            }
        }
        java.util.Map<String, java.util.List<String[]>> byLine = new java.util.TreeMap<>();
        try (var in = getClass().getClassLoader().getResourceAsStream("data/subway/seoulmetro-station-coords_20250814.csv");
             var reader = new java.io.BufferedReader(new java.io.InputStreamReader(in, java.nio.charset.StandardCharsets.UTF_8))) {
            reader.readLine();
            for (String line; (line = reader.readLine()) != null; ) {
                String[] cells = line.split(",", -1);
                byLine.computeIfAbsent(cells[1], key -> new java.util.ArrayList<>()).add(cells);
            }
        }
        java.util.List<String> wrong = new java.util.ArrayList<>();
        int checked = 0;
        for (String lineNo : java.util.List.of("3", "4", "5", "6", "7", "8")) {
            String lineId = "100" + lineNo;
            java.util.List<String[]> rows = byLine.get(lineNo);
            rows.sort(java.util.Comparator.comparingInt(r -> Integer.parseInt(r[0])));
            for (int i = 0; i + 1 < rows.size(); i++) {
                String nameA = rows.get(i)[3].trim();
                String nameB = rows.get(i + 1)[3].trim();
                String a = sidByLineName.get(lineId + ":" + renamed.getOrDefault(nameA, nameA));
                String b = sidByLineName.get(lineId + ":" + renamed.getOrDefault(nameB, nameB));
                checked++;
                if (!Optional.of("하선").equals(SubwayDirectionResolver.resolve(a, b, lineId))
                        || !Optional.of("상선").equals(SubwayDirectionResolver.resolve(b, a, lineId))) {
                    wrong.add(lineNo + "호선 " + rows.get(i)[3] + "→" + rows.get(i + 1)[3]);
                }
            }
        }
        assertTrue(checked > 150, "검사 구간이 너무 적다: " + checked);
        assertTrue(wrong.isEmpty(), "방향이 뒤집힌 구간 " + wrong.size() + "개: " + wrong);
    }
}
