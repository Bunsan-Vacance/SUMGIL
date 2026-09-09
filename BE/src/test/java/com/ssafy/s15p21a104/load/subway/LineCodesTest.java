package com.ssafy.s15p21a104.load.subway;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * line_id 는 서울시 실시간 지하철 API 의 subwayId(4자리)를 쓴다.
 * 수집기가 도착 이벤트를 노선에 붙일 때 변환이 필요 없게 하기 위해서다.
 */
class LineCodesTest {

    @Test
    @DisplayName("서울교통공사 파일의 호선 숫자 → subwayId")
    void seoulMetroLineNumber() {
        assertEquals(Optional.of("1001"), LineCodes.fromSeoulMetroLine("1"));
        assertEquals(Optional.of("1008"), LineCodes.fromSeoulMetroLine("8"));
    }

    @Test
    @DisplayName("환승 파일의 노선 표기 → subwayId")
    void lineNames() {
        assertEquals(Optional.of("1004"), LineCodes.fromName("4호선"));
        assertEquals(Optional.of("1009"), LineCodes.fromName("9호선"));
        assertEquals(Optional.of("1063"), LineCodes.fromName("경의중앙선"));
        assertEquals(Optional.of("1065"), LineCodes.fromName("공항철도"));
        assertEquals(Optional.of("1075"), LineCodes.fromName("수인분당선"));
        assertEquals(Optional.of("1077"), LineCodes.fromName("신분당선"));
        assertEquals(Optional.of("1092"), LineCodes.fromName("우이신설선"));
        assertEquals(Optional.of("1001"), LineCodes.fromName("국철"));
        assertEquals(Optional.of("1001"), LineCodes.fromName("경원선"));
    }

    @Test
    @DisplayName("코레일 구간 파일의 노선 코드 → subwayId (경부·경인·경원선은 1호선, 분당선은 수인분당선)")
    void korailCodes() {
        assertEquals(Optional.of("1001"), LineCodes.fromKorailCode("101"));
        assertEquals(Optional.of("1001"), LineCodes.fromKorailCode("102"));
        assertEquals(Optional.of("1001"), LineCodes.fromKorailCode("108"));
        assertEquals(Optional.of("1063"), LineCodes.fromKorailCode("103"));
        assertEquals(Optional.of("1063"), LineCodes.fromKorailCode("110"));
        assertEquals(Optional.of("1004"), LineCodes.fromKorailCode("104"));
        assertEquals(Optional.of("1004"), LineCodes.fromKorailCode("105"));
        assertEquals(Optional.of("1004"), LineCodes.fromKorailCode("4"));
        assertEquals(Optional.of("1075"), LineCodes.fromKorailCode("106"));
    }

    @Test
    @DisplayName("모르는 표기는 비어 있는 Optional 이다 — 예외로 죽이지 않고 호출자가 보고한다")
    void unknownIsEmpty() {
        assertTrue(LineCodes.fromName("김포골드라인").isEmpty());
        assertTrue(LineCodes.fromKorailCode("999").isEmpty());
        assertTrue(LineCodes.fromSeoulMetroLine("x").isEmpty());
    }

    @Test
    @DisplayName("subwayId → 표시 이름")
    void displayName() {
        assertEquals("2호선", LineCodes.nameOf("1002"));
        assertEquals("경의중앙선", LineCodes.nameOf("1063"));
        assertEquals("수인분당선", LineCodes.nameOf("1075"));
    }

    @Test
    @DisplayName("KTDB RAILLINEN3 표기 → subwayId (서울/서울지하철 접두어, 괄호 설명 제거)")
    void ktdbServiceNames() {
        assertEquals(Optional.of("1002"), LineCodes.fromKtdbServiceName("서울2호선"));
        assertEquals(Optional.of("1009"), LineCodes.fromKtdbServiceName("서울9호선"));
        assertEquals(Optional.of("1009"), LineCodes.fromKtdbServiceName("서울지하철9호선"));
        assertEquals(Optional.of("1067"), LineCodes.fromKtdbServiceName("경춘선(수도권전철)"));
        assertEquals(Optional.of("1063"), LineCodes.fromKtdbServiceName("경의중앙선(수도권전철)"));
    }

    @Test
    @DisplayName("KTDB 수도권 밖 노선은 접두어가 달라 매칭 실패한다 — 우리 노선표 밖이라 의도된 동작")
    void ktdbServiceNamesOutsideRegionAreUnmatched() {
        assertTrue(LineCodes.fromKtdbServiceName("부산1호선").isEmpty());
        assertTrue(LineCodes.fromKtdbServiceName("대구1호선").isEmpty());
        assertTrue(LineCodes.fromKtdbServiceName("인천도시철도1호선").isEmpty());
    }
}
