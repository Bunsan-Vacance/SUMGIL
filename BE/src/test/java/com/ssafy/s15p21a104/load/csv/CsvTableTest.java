package com.ssafy.s15p21a104.load.csv;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** 공공데이터 CSV(헤더 1행, UTF-8, 따옴표 필드 포함)를 읽는 최소 파서 규칙. */
class CsvTableTest {

    @Test
    @DisplayName("헤더를 키로 하는 행 목록을 만든다")
    void parsesHeaderAndRows() {
        CsvTable table = CsvTable.parse("연번,호선,역명\n1,1,서울역\n2,1,시청\n");

        assertEquals(List.of("연번", "호선", "역명"), table.headers());
        assertEquals(2, table.rows().size());
        assertEquals("서울역", table.rows().get(0).get("역명"));
        assertEquals("1", table.rows().get(1).get("호선"));
    }

    @Test
    @DisplayName("UTF-8 BOM과 CRLF, 빈 줄을 무시한다")
    void toleratesBomCrlfAndBlankLines() {
        CsvTable table = CsvTable.parse("﻿a,b\r\n1,2\r\n\r\n3,4\r\n");

        assertEquals(List.of("a", "b"), table.headers());
        assertEquals(2, table.rows().size());
        assertEquals("4", table.rows().get(1).get("b"));
    }

    @Test
    @DisplayName("따옴표 안의 쉼표와 이중 따옴표를 보존한다")
    void handlesQuotedFields() {
        CsvTable table = CsvTable.parse("역이름,관련노선\n서울역,\"경부선(고속),경부선\"\n용산역,\"\"\"별칭\"\" 포함\"\n");

        Map<String, String> first = table.rows().get(0);
        assertEquals("경부선(고속),경부선", first.get("관련노선"));
        assertEquals("\"별칭\" 포함", table.rows().get(1).get("관련노선"));
    }

    @Test
    @DisplayName("열 수가 헤더보다 적은 행은 빈 문자열로 채운다")
    void padsShortRows() {
        CsvTable table = CsvTable.parse("a,b,c\n1,2\n");

        assertEquals("", table.rows().get(0).get("c"));
        assertTrue(table.rows().get(0).containsKey("c"));
    }
}
