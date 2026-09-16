package com.ssafy.s15p21a104.consume;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.temporal.ChronoUnit;

/**
 * Redis 값에 넣는 시각 표기 (S15P21A104-171). 이벤트 계약({@code CollectEventJson})과 같은 규칙이다 —
 * ISO-8601 + 오프셋, 밀리초 이하 절사. 읽는 쪽(192 API)이 두 곳에서 다른 형식을 보지 않게 한 군데로 모은다.
 */
final class Times {

    private static final DateTimeFormatter ISO = DateTimeFormatter.ISO_OFFSET_DATE_TIME;

    private Times() {
    }

    static String format(OffsetDateTime time) {
        return time == null ? null : ISO.format(time.truncatedTo(ChronoUnit.MILLIS));
    }

    /** Redis 에서 읽은 값. 없거나 형식이 다르면 null — 멱등 비교에서 "기존 값 없음"으로 다뤄 새 값을 쓴다. */
    static OffsetDateTime parse(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return OffsetDateTime.parse(value.toString(), ISO);
        } catch (DateTimeParseException e) {
            return null;
        }
    }
}
