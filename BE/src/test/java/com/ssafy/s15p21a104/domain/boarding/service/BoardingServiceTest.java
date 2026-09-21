package com.ssafy.s15p21a104.domain.boarding.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;

import com.ssafy.s15p21a104.domain.boarding.dto.request.BoardingRequest;
import com.ssafy.s15p21a104.domain.boarding.dto.response.BoardingResponse;
import com.ssafy.s15p21a104.domain.boarding.entity.BoardingEvent;
import com.ssafy.s15p21a104.domain.boarding.entity.BoardingStatus;
import com.ssafy.s15p21a104.domain.boarding.repository.BoardingEventRepository;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.time.OffsetDateTime;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class BoardingServiceTest {

    @Mock
    private BoardingEventRepository boardingEventRepository;

    @InjectMocks
    private BoardingService boardingService;

    @Test
    @DisplayName("mode/fromNodeId/toNodeId/status/reportedAt 중 하나라도 없으면 BAD_REQUEST")
    void 필수값_누락시_BAD_REQUEST() {
        BoardingRequest missingMode = new BoardingRequest(
                null, "222", "역삼역", "223", "선릉역", "1002", "2호선",
                BoardingStatus.BOARDED, "09:38", OffsetDateTime.now());

        DomainException exception = assertThrows(DomainException.class,
                () -> boardingService.record(missingMode));

        assertEquals(ErrorType.BAD_REQUEST, exception.getErrorType());
    }

    @Test
    @DisplayName("fromNodeId가 공백이면 BAD_REQUEST")
    void fromNodeId_공백이면_BAD_REQUEST() {
        BoardingRequest blank = new BoardingRequest(
                TravelMode.SUBWAY, "  ", "역삼역", "223", "선릉역", "1002", "2호선",
                BoardingStatus.BOARDED, "09:38", OffsetDateTime.now());

        DomainException exception = assertThrows(DomainException.class,
                () -> boardingService.record(blank));

        assertEquals(ErrorType.BAD_REQUEST, exception.getErrorType());
    }

    @Test
    @DisplayName("정상 요청은 저장하고 응답으로 되돌려준다")
    void 정상요청_저장() {
        OffsetDateTime reportedAt = OffsetDateTime.parse("2026-09-21T09:38:00+09:00");
        BoardingRequest request = new BoardingRequest(
                TravelMode.SUBWAY, "222", "역삼역", "223", "선릉역", "1002", "2호선",
                BoardingStatus.BOARDED, "09:38", reportedAt);
        lenient().when(boardingEventRepository.save(any())).thenAnswer(invocation -> {
            BoardingEvent event = invocation.getArgument(0);
            java.lang.reflect.Field idField = BoardingEvent.class.getDeclaredField("id");
            idField.setAccessible(true);
            idField.set(event, 1L);
            return event;
        });

        BoardingResponse response = boardingService.record(request);

        assertEquals(1L, response.id());
        assertEquals(TravelMode.SUBWAY, response.mode());
        assertEquals("222", response.fromNodeId());
        assertEquals(BoardingStatus.BOARDED, response.status());
        assertEquals("09:38", response.departureTime());
        assertEquals(reportedAt, response.reportedAt());
    }

    @Test
    @DisplayName("status=UNKNOWN이면 departureTime 없이도 저장된다")
    void UNKNOWN상태_저장() {
        OffsetDateTime reportedAt = OffsetDateTime.now();
        BoardingRequest request = new BoardingRequest(
                TravelMode.BUS, "STOP-1", "테헤란로 정류장", "STOP-2", "도곡역", null, null,
                BoardingStatus.UNKNOWN, null, reportedAt);
        lenient().when(boardingEventRepository.save(any())).thenAnswer(invocation -> invocation.getArgument(0));

        BoardingResponse response = boardingService.record(request);

        assertEquals(BoardingStatus.UNKNOWN, response.status());
        assertEquals(null, response.departureTime());
    }
}
