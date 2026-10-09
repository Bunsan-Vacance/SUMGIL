package com.ssafy.s15p21a104.domain.congestion.controller;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionBatchResponse;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.domain.congestion.service.CongestionQueryService;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import com.ssafy.s15p21a104.global.exception.GlobalExceptionHandler;
import java.time.LocalDateTime;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.format.support.DefaultFormattingConversionService;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

/** 스프링 컨텍스트 없이 컨트롤러의 파라미터 바인딩과 예외 응답만 확인한다. */
class CongestionControllerTest {

    private CongestionQueryService service;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        service = mock(CongestionQueryService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(new CongestionController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setConversionService(new DefaultFormattingConversionService())
                .build();
    }

    @Test
    @DisplayName("쉼표 목록과 반복 파라미터, ISO 시각 목록이 서비스에 리스트로 전달된다")
    @SuppressWarnings("unchecked")
    void 목록_바인딩() throws Exception {
        when(service.findBatch(any(), any(), any()))
                .thenReturn(new CongestionBatchResponse(CongestionTarget.STATION, List.of(), List.of()));

        mockMvc.perform(get("/api/congestion/batch")
                        .param("targetType", "STATION")
                        .param("targetIds", "222,333")
                        .param("departureTimes", "2026-09-14T09:10:00,2026-09-14T18:40:00"))
                .andExpect(status().isOk());
        mockMvc.perform(get("/api/congestion/batch")
                        .param("targetType", "STATION")
                        .param("targetIds", "a", "b"))
                .andExpect(status().isOk());

        ArgumentCaptor<List<String>> ids = ArgumentCaptor.forClass(List.class);
        ArgumentCaptor<List<LocalDateTime>> times = ArgumentCaptor.forClass(List.class);
        verify(service, org.mockito.Mockito.times(2))
                .findBatch(eq(CongestionTarget.STATION), ids.capture(), times.capture());
        assertEquals(List.of("222", "333"), ids.getAllValues().get(0));
        assertEquals(
                List.of(LocalDateTime.of(2026, 9, 14, 9, 10), LocalDateTime.of(2026, 9, 14, 18, 40)),
                times.getAllValues().get(0));
        assertEquals(List.of("a", "b"), ids.getAllValues().get(1));
    }

    @Test
    @DisplayName("departureTimes를 생략하면 null이 전달된다")
    @SuppressWarnings("unchecked")
    void 시각_생략() throws Exception {
        when(service.findBatch(any(), any(), any()))
                .thenReturn(new CongestionBatchResponse(CongestionTarget.STATION, List.of(), List.of()));

        mockMvc.perform(get("/api/congestion/batch")
                        .param("targetType", "STATION")
                        .param("targetIds", "222"))
                .andExpect(status().isOk());

        ArgumentCaptor<List<LocalDateTime>> times = ArgumentCaptor.forClass(List.class);
        verify(service).findBatch(eq(CongestionTarget.STATION), any(), times.capture());
        assertNull(times.getValue());
    }

    @Test
    @DisplayName("잘못된 targetType이나 시각 형식은 400이다")
    void 잘못된_파라미터() throws Exception {
        mockMvc.perform(get("/api/congestion/batch")
                        .param("targetType", "FOO")
                        .param("targetIds", "222"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(get("/api/congestion/batch")
                        .param("targetType", "STATION")
                        .param("targetIds", "222")
                        .param("departureTimes", "내일"))
                .andExpect(status().isBadRequest());
        verifyNoInteractions(service);
    }

    @Test
    @DisplayName("상한 초과 예외는 400과 CONGESTION_BATCH_TOO_LARGE 코드로 응답한다")
    void 상한초과_응답() throws Exception {
        when(service.findBatch(any(), any(), any()))
                .thenThrow(new DomainException(ErrorType.CONGESTION_BATCH_TOO_LARGE));

        mockMvc.perform(get("/api/congestion/batch")
                        .param("targetType", "STATION")
                        .param("targetIds", "222"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("CONGESTION_BATCH_TOO_LARGE"));
    }
}
