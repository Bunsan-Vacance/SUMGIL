package com.ssafy.s15p21a104.load.bike;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * bikeList 스냅샷(BE/scripts/data/bike-snapshot.mjs) → bike_station 행.
 * rental_id 는 API 의 stationId(ST-xxx) — API 명세(api-spec.md)·Redis 키(bike:stock:{rentalId})와 같은 값이다.
 * 파일형 대여소 정보(OA-13252)에는 stationId 가 없어 대여소번호(이름 접두어)로 대조만 하고 값은 스냅샷을 쓴다.
 */
class BikeStationParserTest {

    private static Map<String, String> live(String stationId, String stationName, String lat, String lng, String rack) {
        Map<String, String> m = new HashMap<>();
        m.put("stationId", stationId);
        m.put("stationName", stationName);
        m.put("stationLatitude", lat);
        m.put("stationLongitude", lng);
        m.put("rackTotCnt", rack);
        m.put("parkingBikeTotCnt", "5");
        m.put("shared", "33");
        return m;
    }

    private static Map<String, String> file(String no, String name, String lcd, String qr) {
        Map<String, String> m = new HashMap<>();
        m.put("대여소번호", no);
        m.put("보관소명", name);
        m.put("자치구", "마포구");
        m.put("상세주소", "서울특별시 마포구 월드컵로 72");
        m.put("위도", "37.5556488");
        m.put("경도", "126.91062927");
        m.put("설치시기", "42253.987569444442");
        m.put("LCD거치대수", lcd);
        m.put("QR거치대수", qr);
        m.put("운영방식", "QR");
        return m;
    }

    private final BikeStationParser parser = new BikeStationParser();

    @Test
    @DisplayName("stationId 를 rental_id 로 쓰고, 이름의 번호 접두어('102. ')를 떼고, 거치대수는 rackTotCnt 를 쓴다")
    void mapsLiveRow() {
        List<BikeStationRow> out = parser.parse(
                List.of(live("ST-4", "102. 망원역 1번출구 앞", "37.55564880", "126.91062927", "15")), List.of());

        assertEquals(1, out.size());
        BikeStationRow r = out.get(0);
        assertEquals("ST-4", r.rentalId());
        assertEquals("망원역 1번출구 앞", r.name());
        assertEquals(37.5556488, r.lat(), 1e-9);
        assertEquals(126.91062927, r.lng(), 1e-9);
        assertEquals(15, r.dockCount());
    }

    @Test
    @DisplayName("번호 접두어가 없는 이름은 그대로 두고 경고한다 — 파일 대조를 할 수 없기 때문")
    void nameWithoutPrefixWarns() {
        List<BikeStationRow> out = parser.parse(List.of(live("ST-9", "접두어없음", "37.5", "127.0", "10")), List.of());

        assertEquals("접두어없음", out.get(0).name());
        assertEquals(1, parser.warnings().size());
    }

    @Test
    @DisplayName("rackTotCnt 나 좌표가 비어 있으면 null 로 둔다 — 값을 만들어 넣지 않는다")
    void blankValuesBecomeNull() {
        List<BikeStationRow> out = parser.parse(List.of(live("ST-10", "200. 빈값", "", "", "")), List.of());

        assertNull(out.get(0).dockCount());
        assertNull(out.get(0).lat());
        assertNull(out.get(0).lng());
    }

    @Test
    @DisplayName("stationId 가 비어 있는 행은 건너뛰고, 같은 stationId 가 두 번 나오면 두 번째는 건너뛰며 경고한다")
    void blankAndDuplicateIds() {
        List<BikeStationRow> out = parser.parse(List.of(
                live("", "300. 아이디없음", "37.5", "127.0", "10"),
                live("ST-4", "102. 망원역 1번출구 앞", "37.5", "127.0", "15"),
                live("ST-4", "102. 망원역 1번출구 앞", "37.5", "127.0", "15")), List.of());

        assertEquals(1, out.size());
        assertEquals(2, parser.warnings().size());
    }

    @Test
    @DisplayName("파일과 대여소번호로 대조한다 — 파일에 없는 번호, 스냅샷에 없는 번호, 거치대수(LCD+QR) 불일치를 경고로 남긴다")
    void crossChecksWithFile() {
        List<BikeStationRow> out = parser.parse(
                List.of(live("ST-4", "102. 망원역 1번출구 앞", "37.5", "127.0", "15"),
                        live("ST-9", "999. 파일에없음", "37.5", "127.0", "10")),
                List.of(file("102", " 망원역 1번출구 앞", "", "14"),
                        file("555", "스냅샷에없음", "10", "")));

        assertEquals(2, out.size());
        BikeStationParser.CrossCheck cc = parser.crossCheck();
        assertEquals(1, cc.matched());
        assertEquals(List.of("999"), cc.onlyInSnapshot());
        assertEquals(List.of("555"), cc.onlyInFile());
        assertEquals(1, cc.dockMismatch());
        assertTrue(parser.warnings().stream().anyMatch(w -> w.contains("거치대수") && w.contains("102")));
    }

    @Test
    @DisplayName("LCD·QR 거치대수를 합쳐 파일 값으로 본다 — 둘 다 비어 있으면 대조하지 않는다")
    void fileDockCountIsLcdPlusQr() {
        parser.parse(
                List.of(live("ST-4", "102. 망원역 1번출구 앞", "37.5", "127.0", "15"),
                        live("ST-5", "103. 망원역 2번출구 앞", "37.5", "127.0", "14")),
                List.of(file("102", "망원역 1번출구 앞", "5", "10"),
                        file("103", "망원역 2번출구 앞", "", "")));

        assertEquals(0, parser.crossCheck().dockMismatch());
        assertEquals(2, parser.crossCheck().matched());
    }
}
