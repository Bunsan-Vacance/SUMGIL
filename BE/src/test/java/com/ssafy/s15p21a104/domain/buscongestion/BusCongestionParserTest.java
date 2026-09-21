package com.ssafy.s15p21a104.domain.buscongestion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

/**
 * 버스 도착정보 응답 → 노선별 혼잡 등급 파싱 (S15P21A104-297).
 *
 * <p>원천은 공공데이터포털 15000314 `getLowArrInfoByStId`. 등급은 `reride_Num1` 이고
 * 2026-09-21 실측에서 0(정보없음)·3·4 만 관측됐다 — 5·6 은 코드표 기준이다.
 */
class BusCongestionParserTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();

    /** Gradle 테스트의 작업 디렉터리는 BE/ 다 ({@code collect.source.Fixtures} 와 같은 규칙). */
    private static String sample(String name) {
        try {
            return Files.readString(Path.of("docs", "external", "samples", name), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** 응답 한 행. 등급·도착초·노선 ID 만 다르게 준다. */
    private static Map<String, Object> row(String routeId, Object grade, Object arrivalSec, String arrmsg) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("busRouteId", routeId);
        row.put("rtNm", "노선" + routeId);
        row.put("reride_Num1", grade);
        row.put("traTime1", arrivalSec);
        row.put("arrmsg1", arrmsg);
        return row;
    }

    private static String body(Object itemList) {
        Map<String, Object> root = new LinkedHashMap<>();
        root.put("msgHeader", Map.of("headerCd", "0", "headerMsg", "정상적으로 처리되었습니다."));
        Map<String, Object> msgBody = new LinkedHashMap<>();
        msgBody.put("itemList", itemList);
        root.put("msgBody", msgBody);
        return MAPPER.writeValueAsString(root);
    }

    private static String bodyOf(List<Map<String, Object>> rows) {
        return body(rows);
    }

    @Test
    @DisplayName("297-P1: 실측 샘플 — 등급 있는 노선 3개만 남고 코드 0 은 전부 빠진다")
    void p1_실측_샘플() {
        Map<String, BusArrival> out = BusCongestionParser.parse(MAPPER, sample("bus-111000012.json"));

        // 14행 중 reride_Num1 이 0 이 아닌 것은 705·703·571 셋뿐이다.
        assertEquals(3, out.size(), "코드 0(운행종료·출발대기·경기 버스)은 전부 빠져야 한다");
        assertEquals(BusCongestionGrade.RELAXED, out.get("100100587").grade(), "705");
        assertEquals(74, out.get("100100587").arrivalSec());
        assertEquals(BusCongestionGrade.RELAXED, out.get("116000006").grade(), "703");
        assertEquals(196, out.get("116000006").arrivalSec());
        assertEquals(BusCongestionGrade.RELAXED, out.get("100100084").grade(), "571");
        assertFalse(out.containsKey("218000116"), "730고양은 경기 버스라 코드 0 — 값을 지어내지 않는다");
        assertFalse(out.containsKey("123000010"), "741 은 출발대기라 코드 0");
    }

    @Test
    @DisplayName("297-P2: 09-21 실측 형태 — 3 여유 · 4 보통, 0 은 제외")
    void p2_등급_매핑() {
        Map<String, BusArrival> out = BusCongestionParser.parse(MAPPER, bodyOf(List.of(
                row("100100185", "3", "145", "2분25초후[0번째 전]"),
                row("100100087", "4", "312", "5분12초후[2번째 전]"),
                row("229000060", "0", "0", "출발대기"))));

        assertEquals(2, out.size());
        assertEquals(BusCongestionGrade.RELAXED, out.get("100100185").grade());
        assertEquals(BusCongestionGrade.NORMAL, out.get("100100087").grade());
        assertFalse(out.containsKey("229000060"));
    }

    @Test
    @DisplayName("297-P3: 코드 5·6 은 혼잡·매우혼잡으로 읽는다 (미관측, 코드표 기준)")
    void p3_상위_등급() {
        Map<String, BusArrival> out = BusCongestionParser.parse(MAPPER, bodyOf(List.of(
                row("A", "5", "60", "곧 도착"),
                row("B", "6", "90", "곧 도착"))));

        assertEquals(BusCongestionGrade.CONGESTED, out.get("A").grade());
        assertEquals(BusCongestionGrade.SATURATED, out.get("B").grade());
    }

    @Test
    @DisplayName("297-P4: 모르는 코드는 버린다 — 등급을 지어내지 않는다")
    void p4_미지의_코드() {
        Map<String, BusArrival> out = BusCongestionParser.parse(MAPPER, bodyOf(List.of(
                row("A", "7", "60", "곧 도착"),
                row("B", "-1", "60", "곧 도착"),
                row("C", "", "60", "곧 도착"),
                row("D", "abc", "60", "곧 도착"))));

        assertTrue(out.isEmpty(), "0·3·4·5·6 외의 값은 해석하지 않는다");
    }

    @Test
    @DisplayName("297-P5: 같은 노선이 두 행이면 먼저 오는 쪽을 남긴다")
    void p5_노선_중복() {
        Map<String, BusArrival> out = BusCongestionParser.parse(MAPPER, bodyOf(List.of(
                row("A", "5", "600", "10분후"),
                row("A", "3", "120", "2분후"))));

        assertEquals(1, out.size());
        assertEquals(120, out.get("A").arrivalSec());
        assertEquals(BusCongestionGrade.RELAXED, out.get("A").grade(), "먼저 오는 버스의 등급");
    }

    @Test
    @DisplayName("297-P6: 행이 1건이면 배열이 아니라 객체 하나로 온다")
    void p6_단일_객체() {
        Map<String, BusArrival> out = BusCongestionParser.parse(
                MAPPER, body(row("100100185", "4", "145", "2분25초후")));

        assertEquals(1, out.size());
        assertEquals(BusCongestionGrade.NORMAL, out.get("100100185").grade());
    }

    @Test
    @DisplayName("297-P7: itemList 가 없거나 비면 빈 맵 — 예외가 아니다")
    void p7_빈_응답() {
        assertTrue(BusCongestionParser.parse(MAPPER, bodyOf(List.of())).isEmpty());

        String noItemList = MAPPER.writeValueAsString(Map.of(
                "msgHeader", Map.of("headerCd", "0", "headerMsg", "정상"),
                "msgBody", new LinkedHashMap<String, Object>()));
        assertTrue(BusCongestionParser.parse(MAPPER, noItemList).isEmpty());
    }

    @Test
    @DisplayName("297-P8: headerCd 가 0 이 아니면 API 오류로 던진다")
    void p8_API_오류() {
        String error = MAPPER.writeValueAsString(Map.of(
                "msgHeader", Map.of("headerCd", "4", "headerMsg", "결과가 없습니다.")));

        SourceCallException e = assertThrows(SourceCallException.class,
                () -> BusCongestionParser.parse(MAPPER, error));
        assertEquals(SourceCallException.Kind.API_ERROR, e.kind());
    }

    @Test
    @DisplayName("297-P9: 본문이 JSON 이 아니면 파싱 오류로 던진다")
    void p9_JSON_아님() {
        SourceCallException e = assertThrows(SourceCallException.class,
                () -> BusCongestionParser.parse(MAPPER, "<html>service error</html>"));
        assertEquals(SourceCallException.Kind.PARSE, e.kind());
    }

    @Test
    @DisplayName("297-P10: 도착초가 없거나 음수면 맨 뒤로 — 먼저 오는 버스 판정을 망치지 않는다")
    void p10_도착초_결측() {
        List<Map<String, Object>> rows = new ArrayList<>();
        rows.add(row("A", "3", "0", "회차대기"));
        rows.add(row("B", "4", "200", "3분20초후"));
        Map<String, BusArrival> out = BusCongestionParser.parse(MAPPER, bodyOf(rows));

        assertEquals(2, out.size());
        assertTrue(out.get("A").arrivalSec() >= BusArrival.UNKNOWN_ARRIVAL_SEC,
                "0 이하는 알 수 없음으로 두고 정렬에서 뒤로 민다");
        assertEquals(200, out.get("B").arrivalSec());
    }

    @Test
    @DisplayName("297-P11: 노선 ID 가 없는 행은 버린다")
    void p11_노선ID_없음() {
        Map<String, Object> noId = row(null, "3", "60", "곧 도착");
        Map<String, Object> blankId = row("", "3", "60", "곧 도착");

        assertTrue(BusCongestionParser.parse(MAPPER, bodyOf(List.of(noId, blankId))).isEmpty());
    }
}
