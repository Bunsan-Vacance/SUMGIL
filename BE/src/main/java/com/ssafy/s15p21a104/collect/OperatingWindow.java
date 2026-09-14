package com.ssafy.s15p21a104.collect;

import java.time.LocalTime;
import java.time.format.DateTimeParseException;

/**
 * 운영 시간 창 (S15P21A104-170). "HH:mm-HH:mm" 형식, 시작 포함·종료 미포함.
 *
 * <p>하루 1,000회 한도를 발표 시간대에 몰아 쓰기 위한 장치다. 창 밖에서는 폴링을 멈추고,
 * 서비스는 Redis TTL 만료로 자연히 "재고 모름 → 정적값 강등"으로 내려간다 (NFR-A01).
 *
 * <ul>
 *   <li>{@code 07:30-13:00} — 07:30 부터 12:59:59 까지</li>
 *   <li>{@code 22:00-06:00} — 자정을 넘는 창. 22:00 이후 또는 06:00 이전</li>
 *   <li>{@code 00:00-24:00} — 하루 종일. 시작과 종료가 같으면 항상 열려 있는 것으로 본다</li>
 * </ul>
 */
public record OperatingWindow(LocalTime start, LocalTime end) {

    public static final OperatingWindow ALL_DAY = new OperatingWindow(LocalTime.MIDNIGHT, LocalTime.MIDNIGHT);

    public static OperatingWindow parse(String text) {
        if (text == null || text.isBlank()) {
            return ALL_DAY;
        }
        String[] parts = text.trim().split("-");
        if (parts.length != 2) {
            throw new IllegalArgumentException("운영 시간 창은 HH:mm-HH:mm 형식이어야 한다: " + text);
        }
        return new OperatingWindow(parseTime(parts[0]), parseTime(parts[1]));
    }

    private static LocalTime parseTime(String text) {
        String t = text.trim();
        if ("24:00".equals(t)) {
            return LocalTime.MIDNIGHT;
        }
        try {
            return LocalTime.parse(t);
        } catch (DateTimeParseException e) {
            throw new IllegalArgumentException("시각 형식이 HH:mm 이 아니다: " + text, e);
        }
    }

    public boolean isAllDay() {
        return start.equals(end);
    }

    public boolean contains(LocalTime time) {
        if (isAllDay()) {
            return true;
        }
        if (start.isBefore(end)) {
            return !time.isBefore(start) && time.isBefore(end);
        }
        // 자정을 넘는 창
        return !time.isBefore(start) || time.isBefore(end);
    }

    /** 창이 하루에 열려 있는 시간(분). 예산 계산·로그용. */
    public long minutesPerDay() {
        if (isAllDay()) {
            return 24 * 60;
        }
        long minutes = (end.toSecondOfDay() - start.toSecondOfDay()) / 60;
        return minutes > 0 ? minutes : minutes + 24 * 60;
    }

    @Override
    public String toString() {
        if (isAllDay()) {
            return "00:00-24:00";
        }
        return start + "-" + (end.equals(LocalTime.MIDNIGHT) ? "24:00" : end.toString());
    }
}
