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
        assertEquals(Optional.of("1065"), LineCodes.fromName("인천국제공항선"));
        assertEquals(Optional.of("1004"), LineCodes.fromName("안산과천선"));
        assertEquals(Optional.of("1003"), LineCodes.fromName("일산선"));
    }

    @Test
    @DisplayName("도시철도 전체노선 파일의 노선명 → subwayId — '선'이 빠진 표기(경의중앙·경춘·신분당)와 '공항'을 받는다")
    void urbanLineNames() {
        assertEquals(Optional.of("1063"), LineCodes.fromUrbanLineName("경의중앙"));
        assertEquals(Optional.of("1075"), LineCodes.fromUrbanLineName("수인분당"));
        assertEquals(Optional.of("1067"), LineCodes.fromUrbanLineName("경춘"));
        assertEquals(Optional.of("1081"), LineCodes.fromUrbanLineName("경강"));
        assertEquals(Optional.of("1093"), LineCodes.fromUrbanLineName("서해선"));
        assertEquals(Optional.of("1065"), LineCodes.fromUrbanLineName("공항"));
        assertEquals(Optional.of("1077"), LineCodes.fromUrbanLineName("신분당"));
        assertEquals(Optional.of("1092"), LineCodes.fromUrbanLineName("우이신설"));
        assertEquals(Optional.of("1094"), LineCodes.fromUrbanLineName("신림선"));
        assertEquals(Optional.of("1002"), LineCodes.fromUrbanLineName("2호선"));
        assertTrue(LineCodes.fromUrbanLineName("인천1호선").isEmpty());
        assertTrue(LineCodes.fromUrbanLineName("GTX-A").isEmpty());
    }

    @Test
    @DisplayName("표준데이터 노선번호 → subwayId. 서비스 노선이 여럿인 물리 선로(I4102 경원선)와 코드 없는 노선(김포·인천)은 비어 있다")
    void stdLineCodes() {
        assertEquals(Optional.of("1063"), LineCodes.fromStdLineCode("I4108"));
        assertEquals(Optional.of("1075"), LineCodes.fromStdLineCode("I4105"));
        assertEquals(Optional.of("1075"), LineCodes.fromStdLineCode("I28K1"));
        assertEquals(Optional.of("1067"), LineCodes.fromStdLineCode("I41K2"));
        assertEquals(Optional.of("1081"), LineCodes.fromStdLineCode("I41K5"));
        assertEquals(Optional.of("1093"), LineCodes.fromStdLineCode("I41WS"));
        assertEquals(Optional.of("1065"), LineCodes.fromStdLineCode("I28A1"));
        assertEquals(Optional.of("1077"), LineCodes.fromStdLineCode("I11D1"));
        assertEquals(Optional.of("1092"), LineCodes.fromStdLineCode("L11UI"));
        assertEquals(Optional.of("1094"), LineCodes.fromStdLineCode("L11SL"));
        assertEquals(Optional.of("1002"), LineCodes.fromStdLineCode("S1102"));
        assertEquals(Optional.of("1004"), LineCodes.fromStdLineCode("I4103"));
        assertTrue(LineCodes.fromStdLineCode("I4102").isEmpty());
        assertTrue(LineCodes.fromStdLineCode("L41G1").isEmpty());
        assertTrue(LineCodes.fromStdLineCode(null).isEmpty());
    }

    @Test
    @DisplayName("모르는 표기는 비어 있는 Optional 이다 — 예외로 죽이지 않고 호출자가 보고한다")
    void unknownIsEmpty() {
        assertTrue(LineCodes.fromName("김포골드라인").isEmpty());
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
