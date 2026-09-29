package com.ssafy.s15p21a104.global.exception;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Getter;
import lombok.RequiredArgsConstructor;

@Getter
@RequiredArgsConstructor
@JsonFormat(shape = JsonFormat.Shape.OBJECT)
public enum ErrorType {

    BAD_REQUEST(400, "BAD_REQUEST", "잘못된 요청입니다."),
    NOT_FOUND(404, "NOT_FOUND", "요청한 리소스를 찾을 수 없습니다."),
    METHOD_NOT_ALLOWED(405, "METHOD_NOT_ALLOWED", "지원하지 않는 메서드입니다."),
    INTERNAL_SERVER_ERROR(500, "INTERNAL_SERVER_ERROR", "서버 오류가 발생했습니다."),

    SAME_ORIGIN_DEST(400, "SAME_ORIGIN_DEST", "출발지와 도착지가 같습니다."),
    STATION_NOT_FOUND(404, "STATION_NOT_FOUND", "역을 찾을 수 없습니다."),
    ROUTE_NOT_FOUND(404, "ROUTE_NOT_FOUND", "경로를 찾을 수 없습니다."),
    INVALID_COORDINATE(400, "INVALID_COORDINATE", "좌표가 유효하지 않습니다."),
    ACCESS_CANDIDATE_NOT_FOUND(404, "ACCESS_CANDIDATE_NOT_FOUND", "좌표 주변 보행 접근 가능한 교통망 후보를 찾을 수 없습니다."),
    ROUTE_DATA_NOT_READY(503, "ROUTE_DATA_NOT_READY", "교통망 데이터가 아직 준비되지 않았습니다."),
    BIKE_STATION_NOT_FOUND(404, "BIKE_STATION_NOT_FOUND", "대여소를 찾을 수 없습니다."),
    ROUTE_SEARCH_BUSY(503, "ROUTE_SEARCH_BUSY", "지금 경로 검색 요청이 많아 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.");

    private final int status;
    private final String code;
    private final String message;
}
