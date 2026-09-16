package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 좌표 원천 4종을 우선순위·다수결·교차검증으로 합쳐 적재용 좌표 목록을 만든다
 * (data/subway/README.md "좌표 결정 규칙"). 규칙이 코드 한 곳에 모여 있어야 원천을 더할 때 깨지지 않는다.
 * <p>
 * 픽스처는 실제 원천 값이다 — 용답은 서울교통공사 파일에 시청 좌표가 들어가 있고(6.4 km, S15P21A104-114),
 * 한국항공대는 국가철도공단 파일이 5 km 어긋나 있다(113).
 */
class StationCoordResolverTest {

    private static final double WARN_M = 500;
    private static final double REPLACE_M = 5000;

    private static StationCoord coord(String lineId, String name, double lat, double lng) {
        return new StationCoord(lineId, name, lat, lng, null);
    }

    /** 빌더와 같은 규칙으로 최종 좌표를 고른다: 목록 앞쪽이 이긴다(같은 이름의 첫 값). */
    private static Optional<StationCoord> pick(List<StationCoord> coords, String name) {
        return coords.stream().filter(c -> c.stationName().equals(name)).findFirst();
    }

    @Test
    @DisplayName("우선순위: 같은 역이 여러 원천에 있으면 서울교통공사 → 국가철도공단 → 표준데이터 → KTDB 순으로 앞선 값을 쓴다")
    void priorityOrder() {
        var result = StationCoordResolver.resolve(
                List.of(coord("1002", "시청", 37.565, 126.977)),
                List.of(coord("1002", "시청", 37.5651, 126.9771), coord("1063", "양정", 37.591, 127.196)),
                List.of(coord("1002", "시청", 37.5652, 126.9772), coord("1077", "판교", 37.394, 127.111)),
                List.of(coord(null, "시청", 37.5653, 126.9773), coord(null, "논현", 37.510, 127.022)),
                WARN_M, REPLACE_M);

        assertEquals(37.565, pick(result.coords(), "시청").orElseThrow().lat());
        assertEquals(37.591, pick(result.coords(), "양정").orElseThrow().lat());
        assertEquals(37.394, pick(result.coords(), "판교").orElseThrow().lat());
        assertEquals(37.510, pick(result.coords(), "논현").orElseThrow().lat());
    }

    @Test
    @DisplayName("서울교통공사 파일에 섞여 들어간 타 역 좌표를 다수결로 정정한다 — 용답 행의 시청 좌표(6.4 km), 표준·KTDB 는 30 m 일치")
    void votesOnSeoulMetroSource() {
        var result = StationCoordResolver.resolve(
                List.of(coord("1002", "용답", 37.566412, 126.977863), coord("1002", "성수", 37.544628, 127.055983)),
                List.of(),
                List.of(coord("1002", "용답", 37.562066, 127.050879), coord("1002", "성수", 37.544700, 127.056000)),
                List.of(coord(null, "용답", 37.562225, 127.050603), coord(null, "성수", 37.544650, 127.055990)),
                WARN_M, REPLACE_M);

        assertEquals(37.562066, pick(result.coords(), "용답").orElseThrow().lat());
        assertEquals(127.050879, pick(result.coords(), "용답").orElseThrow().lng());
        assertEquals("1002", pick(result.coords(), "용답").orElseThrow().lineId());
        assertEquals(37.544628, pick(result.coords(), "성수").orElseThrow().lat());
        assertEquals(List.of("용답"), result.seoulVote().replaced());
        assertTrue(result.seoulVote().warnings().get(0).contains("용답"));
    }

    @Test
    @DisplayName("국가철도공단 파일의 오기도 다수결로 정정한다 — 한국항공대 5.0 km (113 회귀)")
    void votesOnKricSource() {
        var result = StationCoordResolver.resolve(
                List.of(),
                List.of(coord("1063", "한국항공대", 37.637837, 126.832503)),
                List.of(coord("1063", "한국항공대", 37.603102, 126.868291)),
                List.of(coord(null, "한국항공대", 37.603419, 126.867672)),
                WARN_M, REPLACE_M);

        assertEquals(37.603102, pick(result.coords(), "한국항공대").orElseThrow().lat());
        assertEquals(List.of("한국항공대"), result.kricVote().replaced());
    }

    @Test
    @DisplayName("서울교통공사가 덮는 역의 국가철도공단 좌표는 교차검증 대상이 아니다 — 쓰이지 않는 값으로 경고를 내지 않는다")
    void kricCoveredBySeoulMetroIsNotCrossChecked() {
        var result = StationCoordResolver.resolve(
                List.of(coord("1006", "구산", 37.6122, 126.9174)),
                List.of(coord("1006", "구산", 37.5906, 126.9176)),
                List.of(),
                List.of(),
                WARN_M, REPLACE_M);

        assertEquals(37.6122, pick(result.coords(), "구산").orElseThrow().lat());
        assertTrue(result.kricVote().warnings().isEmpty());
        assertTrue(result.crossCheck().warnings().isEmpty());
    }

    @Test
    @DisplayName("표준데이터는 앞 원천에 없는 역만 쓴다 — 그 수를 stdUsed 로 돌려준다 (적재 로그용)")
    void standardFillsOnlyMissingStations() {
        var result = StationCoordResolver.resolve(
                List.of(coord("1002", "시청", 37.565, 126.977)),
                List.of(coord("1063", "양정", 37.591, 127.196)),
                List.of(coord("1002", "시청", 37.5652, 126.9772), coord("1063", "양정", 37.5911, 127.1961),
                        coord("1094", "관악산", 37.4692, 126.9436)),
                List.of(),
                WARN_M, REPLACE_M);

        assertEquals(1, result.stdUsed());
        assertEquals(37.4692, pick(result.coords(), "관악산").orElseThrow().lat());
    }

    @Test
    @DisplayName("5 km 를 넘게 어긋나면 목록에서 빼 KTDB 가 채운다 — 다수결이 판정하지 못한 역(표준데이터 없음)")
    void grosslyWrongCoordFallsBackToKtdb() {
        var result = StationCoordResolver.resolve(
                List.of(),
                List.of(coord("1001", "청산", 37.73873, 127.04589)),
                List.of(),
                List.of(coord(null, "청산", 37.99511, 127.07430)),
                WARN_M, REPLACE_M);

        assertEquals(37.99511, pick(result.coords(), "청산").orElseThrow().lat());
        assertEquals(List.of("청산"), result.crossCheck().replaced());
    }

    @Test
    @DisplayName("원본 4종을 우선순위 순서로 돌려준다 — 적재 로그의 '역 좌표 출처' 집계가 대체 전 값으로 출처를 되짚기 위해서다")
    void exposesOriginalSourcesInPriorityOrder() {
        List<StationCoord> seoul = List.of(coord("1002", "용답", 37.566412, 126.977863));
        List<StationCoord> kric = List.of(coord("1063", "양정", 37.591, 127.196));
        List<StationCoord> std = List.of(coord("1002", "용답", 37.562066, 127.050879));
        List<StationCoord> ktdb = List.of(coord(null, "용답", 37.562225, 127.050603));

        var result = StationCoordResolver.resolve(seoul, kric, std, ktdb, WARN_M, REPLACE_M);

        assertEquals(List.of(seoul, kric, std, ktdb), result.sourcesInPriority());
    }
}
