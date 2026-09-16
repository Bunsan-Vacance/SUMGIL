package com.ssafy.s15p21a104.collect.source;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import tools.jackson.databind.json.JsonMapper;

/** 테스트 입력. 실측 샘플(docs/external/samples, probe --save 산출물)은 파일로, 없는 것은 코드로 만든다. */
final class Fixtures {

    static final JsonMapper MAPPER = JsonMapper.builder().build();

    private Fixtures() {
    }

    /** probe 가 저장한 실측 샘플. Gradle 테스트의 작업 디렉터리는 BE/ 다. */
    static String sample(String name) {
        try {
            return Files.readString(Path.of("docs", "external", "samples", name), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    static String resource(String path) {
        try (InputStream in = Fixtures.class.getResourceAsStream(path)) {
            if (in == null) {
                throw new IllegalArgumentException("테스트 리소스 없음: " + path);
            }
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** 지하철 일괄 응답 모양. rows 개 행, errorMessage.total 지정. */
    static String subwayPage(int rows, long total, int firstRowNum) {
        Map<String, Object> head = new LinkedHashMap<>();
        head.put("status", 200);
        head.put("code", "INFO-000");
        head.put("message", "정상 처리되었습니다.");
        head.put("total", total);
        List<Map<String, Object>> list = new ArrayList<>();
        for (int i = 0; i < rows; i++) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("rowNum", firstRowNum + i);
            row.put("subwayId", "1002");
            row.put("statnId", "10020" + String.format("%05d", firstRowNum + i));
            row.put("statnNm", "역" + (firstRowNum + i));
            row.put("recptnDt", "2026-09-14 09:00:0" + (i % 10));
            row.put("barvlDt", String.valueOf(30 + i));
            list.add(row);
        }
        return MAPPER.writeValueAsString(Map.of("errorMessage", head, "realtimeArrivalList", list));
    }

    static String subwayError(String code, String message) {
        return MAPPER.writeValueAsString(Map.of("status", 500, "code", code, "message", message));
    }

    /** bikeList 응답 모양. rows 개 행, 대여소 번호는 firstStation 부터. */
    static String bikePage(int rows, int firstStation) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (int i = 0; i < rows; i++) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("rackTotCnt", "15");
            row.put("stationName", (firstStation + i) + ". 대여소");
            row.put("parkingBikeTotCnt", String.valueOf(i % 12));
            row.put("shared", "33");
            row.put("stationLatitude", "37.55564880");
            row.put("stationLongitude", "126.91062927");
            row.put("stationId", "ST-" + (firstStation + i));
            list.add(row);
        }
        Map<String, Object> wrap = new LinkedHashMap<>();
        wrap.put("list_total_count", rows);
        wrap.put("RESULT", Map.of("CODE", "INFO-000", "MESSAGE", "정상 처리되었습니다."));
        wrap.put("row", list);
        return MAPPER.writeValueAsString(Map.of("rentBikeStatus", wrap));
    }

    static String bikeError(String code, String message) {
        return MAPPER.writeValueAsString(Map.of("RESULT", Map.of("CODE", code, "MESSAGE", message)));
    }
}
