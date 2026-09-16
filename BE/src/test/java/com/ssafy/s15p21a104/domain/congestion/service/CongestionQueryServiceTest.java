package com.ssafy.s15p21a104.domain.congestion.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionResponse;
import com.ssafy.s15p21a104.domain.congestion.entity.Congestion;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionId;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionRepository;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class CongestionQueryServiceTest {

    @Mock
    private CongestionRepository congestionRepository;

    private CongestionQueryService service() {
        return new CongestionQueryService(congestionRepository);
    }

    @Test
    @DisplayName("데이터가 있으면 congestion 테이블 값을 그대로 응답한다")
    void 조회_성공() {
        Congestion congestion = mockCongestion(
                CongestionTarget.STATION, "222", 0, 18, BigDecimal.valueOf(72.5), "AI");
        // 2026-09-14는 월요일(dowType=0). 09:10 -> timeSlot 18.
        LocalDateTime weekdayMorning = LocalDateTime.of(2026, 9, 14, 9, 10);
        lenient().when(congestionRepository
                        .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                                CongestionTarget.STATION, "222", 0, 18))
                .thenReturn(Optional.of(congestion));

        CongestionResponse result = service().find(CongestionTarget.STATION, "222", weekdayMorning);

        assertEquals(CongestionTarget.STATION, result.targetType());
        assertEquals("222", result.targetId());
        assertEquals(0, result.dowType());
        assertEquals(18, result.timeSlot());
        assertEquals(0, BigDecimal.valueOf(72.5).compareTo(result.level()));
        assertEquals("AI", result.source());
    }

    @Test
    @DisplayName("데이터 없는 조합이면 에러 없이 null을 반환한다(값을 지어내지 않음)")
    void 데이터없음_null() {
        when(congestionRepository
                .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                        any(), anyString(), any(), any()))
                .thenReturn(Optional.empty());

        CongestionResponse result = service().find(
                CongestionTarget.STATION, "9999", LocalDateTime.of(2026, 9, 14, 9, 10));

        assertNull(result);
    }

    @Test
    @DisplayName("LINE(노선) 대상도 STATION과 같은 방식으로 조회된다")
    void 조회_성공_LINE() {
        Congestion congestion = mockCongestion(
                CongestionTarget.LINE, "1002", 0, 18, BigDecimal.valueOf(55.0), "AI");
        LocalDateTime weekdayMorning = LocalDateTime.of(2026, 9, 14, 9, 10);
        lenient().when(congestionRepository
                        .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                                CongestionTarget.LINE, "1002", 0, 18))
                .thenReturn(Optional.of(congestion));

        CongestionResponse result = service().find(CongestionTarget.LINE, "1002", weekdayMorning);

        assertEquals(CongestionTarget.LINE, result.targetType());
        assertEquals("1002", result.targetId());
        assertEquals(0, BigDecimal.valueOf(55.0).compareTo(result.level()));
    }

    @Test
    @DisplayName("존재하지 않는 targetId(LINE)도 데이터 없음으로 처리된다(값을 지어내지 않음)")
    void 존재하지않는_LINE_ID_null() {
        when(congestionRepository
                .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                        any(), anyString(), any(), any()))
                .thenReturn(Optional.empty());

        CongestionResponse result = service().find(
                CongestionTarget.LINE, "9999", LocalDateTime.of(2026, 9, 14, 9, 10));

        assertNull(result);
    }

    @Test
    @DisplayName("시각 미지정 시 현재 시각 기준 슬롯으로 조회한다")
    void 시각미지정_현재시각기준() {
        when(congestionRepository
                .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                        any(), anyString(), any(), any()))
                .thenReturn(Optional.empty());

        service().find(CongestionTarget.STATION, "222", null);

        verify(congestionRepository).findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                org.mockito.ArgumentMatchers.eq(CongestionTarget.STATION),
                org.mockito.ArgumentMatchers.eq("222"),
                any(), any());
    }

    private Congestion mockCongestion(
            CongestionTarget targetType, String targetId, int dowType, int timeSlot,
            BigDecimal level, String source) {
        Congestion congestion = org.mockito.Mockito.mock(Congestion.class);
        CongestionId id = new CongestionId(targetType, targetId, dowType, timeSlot);
        lenient().when(congestion.getId()).thenReturn(id);
        lenient().when(congestion.getLevel()).thenReturn(level);
        lenient().when(congestion.getSource()).thenReturn(source);
        lenient().when(congestion.getUpdatedAt()).thenReturn(OffsetDateTime.now());
        return congestion;
    }
}
