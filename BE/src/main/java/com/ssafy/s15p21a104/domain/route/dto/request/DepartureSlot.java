package com.ssafy.s15p21a104.domain.route.dto.request;

import java.time.DayOfWeek;
import java.time.LocalDateTime;

/**
 * 요청 시각을 {@code edge_time} 조회 키(dow_type, time_slot)로 바꾼다.
 *
 * <p>dow_type: 0 평일 / 1 토 / 2 일요일·공휴일 — 공휴일 캘린더가 없어 당장은 요일만으로 판정한다
 * (요청 문서 "요일 유형 판정" 참고, 공휴일 캘린더 도입 시 이 판정만 바꾸면 된다).
 * time_slot: 0~47, 30분 단위(0시부터).
 */
public record DepartureSlot(int dowType, int timeSlot) {

    public static DepartureSlot of(LocalDateTime dateTime) {
        int dowType = dateTime.getDayOfWeek() == DayOfWeek.SATURDAY ? 1
                : dateTime.getDayOfWeek() == DayOfWeek.SUNDAY ? 2
                : 0;
        int timeSlot = dateTime.getHour() * 2 + (dateTime.getMinute() >= 30 ? 1 : 0);
        return new DepartureSlot(dowType, timeSlot);
    }
}
