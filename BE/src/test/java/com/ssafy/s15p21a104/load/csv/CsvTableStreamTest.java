package com.ssafy.s15p21a104.load.csv;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.StringReader;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 42만 행짜리 시각표를 통째로 올리지 않고 행마다 콜백으로 넘기는 스트리밍 읽기.
 * 규칙(따옴표·BOM·CRLF·빈 줄)은 parse(String) 과 같아야 한다.
 */
class CsvTableStreamTest {

    private static final String CSV = "﻿역이름,관련노선\r\n서울역,\"경부선(고속),경부선\"\r\n\r\n용산역,\"\"\"별칭\"\" 포함\"\n"
            + "\"여러\n줄\",x\n";

    private static List<Map<String, String>> stream(String text) {
        List<Map<String, String>> out = new ArrayList<>();
        CsvTable.forEachRow(new StringReader(text), out::add);
        return out;
    }

    @Test
    @DisplayName("스트리밍 결과는 parse(String) 과 같다 — BOM·CRLF·빈 줄·따옴표 안 쉼표·이중 따옴표·따옴표 안 줄바꿈")
    void matchesParse() {
        List<Map<String, String>> streamed = stream(CSV);
        List<Map<String, String>> parsed = CsvTable.parse(CSV).rows();

        assertEquals(parsed, streamed);
        assertEquals(3, streamed.size());
        assertEquals("경부선(고속),경부선", streamed.get(0).get("관련노선"));
        assertEquals("\"별칭\" 포함", streamed.get(1).get("관련노선"));
        assertEquals("여러\n줄", streamed.get(2).get("역이름"));
    }

    @Test
    @DisplayName("헤더보다 짧은 행은 빈 문자열로 채우고, 헤더만 있으면 콜백이 없다")
    void padsShortRowsAndHandlesHeaderOnly() {
        List<Map<String, String>> rows = stream("a,b,c\n1,2\n");

        assertEquals(1, rows.size());
        assertEquals("", rows.get(0).get("c"));
        assertEquals(0, stream("a,b\n").size());
    }
}
