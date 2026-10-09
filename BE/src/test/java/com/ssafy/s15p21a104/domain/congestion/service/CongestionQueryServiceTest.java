package com.ssafy.s15p21a104.domain.congestion.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionBatchResponse;
import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionBatchSlot;
import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionResponse;
import com.ssafy.s15p21a104.domain.congestion.entity.Congestion;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionId;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionRepository;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
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

    // 2026-09-14는 월요일(평일 0), 2026-09-19는 토요일(1).
    private static final LocalDateTime MON_0910 = LocalDateTime.of(2026, 9, 14, 9, 10);
    private static final LocalDateTime MON_1840 = LocalDateTime.of(2026, 9, 14, 18, 40);
    private static final LocalDateTime SAT_0910 = LocalDateTime.of(2026, 9, 19, 9, 10);

    private final List<Congestion> table = new ArrayList<>();

    /** 일괄·단건 리포지토리 mock을 같은 표(table)에서 인자에 맞는 행만 돌려주도록 구성한다. */
    private void stubTable() {
        table.add(mockCongestion(CongestionTarget.STATION, "A", 0, 18, BigDecimal.valueOf(70.0), "AI"));
        table.add(mockCongestion(CongestionTarget.STATION, "A", 0, 37, BigDecimal.valueOf(90.0), "AI"));
        table.add(mockCongestion(CongestionTarget.STATION, "A", 1, 37, BigDecimal.valueOf(10.0), "AI"));
        table.add(mockCongestion(CongestionTarget.STATION, "B", 0, 18, BigDecimal.valueOf(40.0), "OFFICIAL"));
        table.add(mockCongestion(CongestionTarget.STATION, "B", 1, 18, BigDecimal.valueOf(30.0), "AI"));
        lenient().when(congestionRepository
                        .findById_TargetTypeAndId_TargetIdInAndId_DowTypeInAndId_TimeSlotIn(
                                eq(CongestionTarget.STATION), anyCollection(), anyCollection(), anyCollection()))
                .thenAnswer(invocation -> {
                    Collection<String> ids = invocation.getArgument(1);
                    Collection<Integer> dows = invocation.getArgument(2);
                    Collection<Integer> slots = invocation.getArgument(3);
                    return table.stream()
                            .filter(c -> ids.contains(c.getId().getTargetId())
                                    && dows.contains(c.getId().getDowType())
                                    && slots.contains(c.getId().getTimeSlot()))
                            .toList();
                });
        lenient().when(congestionRepository
                        .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                                eq(CongestionTarget.STATION), anyString(), any(), any()))
                .thenAnswer(invocation -> table.stream()
                        .filter(c -> c.getId().getTargetId().equals(invocation.getArgument(1))
                                && c.getId().getDowType().equals(invocation.getArgument(2))
                                && c.getId().getTimeSlot().equals(invocation.getArgument(3)))
                        .findFirst());
    }

    private static List<String> ids(int count) {
        List<String> result = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            result.add("T" + i);
        }
        return result;
    }

    private static List<LocalDateTime> timeList(int count) {
        List<LocalDateTime> result = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            result.add(LocalDateTime.of(2026, 9, 14, 0, 0).plusMinutes(30L * i));
        }
        return result;
    }

    @Test
    @DisplayName("일괄 조회 결과가 단건 조회 6번과 모든 조합에서 같다")
    void 일괄_단건_대조() {
        stubTable();
        List<LocalDateTime> requested = List.of(MON_0910, MON_1840, SAT_0910);

        CongestionBatchResponse batch = service().findBatch(
                CongestionTarget.STATION, List.of("A", "B"), requested);

        for (var target : batch.targets()) {
            for (int i = 0; i < requested.size(); i++) {
                CongestionResponse single = service().find(
                        CongestionTarget.STATION, target.targetId(), requested.get(i));
                CongestionBatchSlot slot = target.slots().get(i);
                if (single == null) {
                    assertNull(slot.level());
                    assertNull(slot.source());
                    assertNull(slot.updatedAt());
                } else {
                    assertEquals(single.dowType(), slot.dowType());
                    assertEquals(single.timeSlot(), slot.timeSlot());
                    assertEquals(0, single.level().compareTo(slot.level()));
                    assertEquals(single.source(), slot.source());
                }
            }
        }
    }

    @Test
    @DisplayName("값 없는 조합도 null 행으로 남고 요청한 조합 밖의 행은 섞이지 않는다")
    void 일괄_빈조합_null행() {
        stubTable();

        CongestionBatchResponse batch = service().findBatch(
                CongestionTarget.STATION, List.of("A", "B"), List.of(MON_0910, MON_1840, SAT_0910));

        assertEquals(2, batch.targets().size());
        batch.targets().forEach(target -> assertEquals(3, target.slots().size()));
        // A는 토요일 09:10(1,18) 데이터가 없다. (1,37) 행은 요청한 조합이 아니므로 나타나지 않는다.
        CongestionBatchSlot aSat = batch.targets().get(0).slots().get(2);
        assertEquals(1, aSat.dowType());
        assertEquals(18, aSat.timeSlot());
        assertNull(aSat.level());
        // B는 월요일 18:40(0,37) 데이터가 없다.
        assertNull(batch.targets().get(1).slots().get(1).level());
    }

    @Test
    @DisplayName("대상·시각 순서는 요청 순서를 따른다")
    void 일괄_순서보장() {
        stubTable();

        CongestionBatchResponse batch = service().findBatch(
                CongestionTarget.STATION, List.of("B", "A"), List.of(SAT_0910, MON_0910));

        assertEquals(List.of("B", "A"), batch.targets().stream().map(t -> t.targetId()).toList());
        assertEquals(List.of(SAT_0910, MON_0910), batch.departureTimes());
        assertEquals(
                List.of(SAT_0910, MON_0910),
                batch.targets().get(0).slots().stream().map(CongestionBatchSlot::departureTime).toList());
    }

    @Test
    @DisplayName("공백·빈 항목·중복 대상과 중복 시각을 정리한다")
    void 일괄_정규화() {
        stubTable();

        CongestionBatchResponse batch = service().findBatch(
                CongestionTarget.STATION,
                java.util.Arrays.asList(" A ", "", "  ", null, "A", "B"),
                List.of(MON_0910, MON_0910));

        assertEquals(List.of("A", "B"), batch.targets().stream().map(t -> t.targetId()).toList());
        assertEquals(List.of(MON_0910), batch.departureTimes());
    }

    @Test
    @DisplayName("대상 51개·시각 13개·조합 220개는 CONGESTION_BATCH_TOO_LARGE")
    void 일괄_상한초과() {
        assertEquals(ErrorType.CONGESTION_BATCH_TOO_LARGE, assertThrows(DomainException.class,
                () -> service().findBatch(CongestionTarget.STATION, ids(51), List.of(MON_0910)))
                .getErrorType());
        assertEquals(ErrorType.CONGESTION_BATCH_TOO_LARGE, assertThrows(DomainException.class,
                () -> service().findBatch(CongestionTarget.STATION, ids(1), timeList(13)))
                .getErrorType());
        assertEquals(ErrorType.CONGESTION_BATCH_TOO_LARGE, assertThrows(DomainException.class,
                () -> service().findBatch(CongestionTarget.STATION, ids(20), timeList(11)))
                .getErrorType());
    }

    @Test
    @DisplayName("정리 후 대상이 비면 BAD_REQUEST")
    void 일괄_빈대상() {
        assertEquals(ErrorType.BAD_REQUEST, assertThrows(DomainException.class,
                () -> service().findBatch(CongestionTarget.STATION, List.of(" ", ""), List.of(MON_0910)))
                .getErrorType());
        assertEquals(ErrorType.BAD_REQUEST, assertThrows(DomainException.class,
                () -> service().findBatch(CongestionTarget.STATION, null, List.of(MON_0910)))
                .getErrorType());
    }

    @Test
    @DisplayName("시각을 생략하면 현재 시각 하나로 조회한다")
    void 일괄_시각생략() {
        stubTable();

        assertEquals(1, service().findBatch(CongestionTarget.STATION, List.of("A"), null)
                .departureTimes().size());
        assertEquals(1, service().findBatch(CongestionTarget.STATION, List.of("A"), List.of())
                .departureTimes().size());
    }

    @Test
    @DisplayName("일괄 조회는 리포지토리를 한 번만 호출하고 단건 메서드는 부르지 않는다")
    void 일괄_쿼리1회() {
        stubTable();

        service().findBatch(CongestionTarget.STATION, List.of("A", "B"), List.of(MON_0910, SAT_0910));

        verify(congestionRepository, times(1))
                .findById_TargetTypeAndId_TargetIdInAndId_DowTypeInAndId_TimeSlotIn(
                        eq(CongestionTarget.STATION), anyCollection(), anyCollection(), anyCollection());
        verify(congestionRepository, never())
                .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(any(), any(), any(), any());
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
