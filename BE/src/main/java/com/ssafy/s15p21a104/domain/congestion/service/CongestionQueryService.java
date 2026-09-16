package com.ssafy.s15p21a104.domain.congestion.service;

import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionResponse;
import com.ssafy.s15p21a104.domain.congestion.entity.Congestion;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionRepository;
import com.ssafy.s15p21a104.domain.route.dto.request.DepartureSlot;
import java.time.LocalDateTime;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 혼잡도 조회(S15P21A104-150). 대상·시간대로 {@code congestion} 테이블 값을 그대로 꺼낸다.
 *
 * <p>데이터 없는 조합은 에러가 아니라 {@code null} — 컨트롤러가 {@code 200 + data 없음}으로 응답한다.
 * 값을 추정·보간하지 않는다.
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class CongestionQueryService {

    private final CongestionRepository congestionRepository;

    /**
     * @param targetType 대상 종류(역/노선 등)
     * @param targetId 대상 ID
     * @param departureTime 기준 시각. 생략 시 현재 시각
     * @return 조회된 혼잡도. 데이터 없으면 {@code null}
     */
    public CongestionResponse find(CongestionTarget targetType, String targetId, LocalDateTime departureTime) {
        DepartureSlot slot = DepartureSlot.of(departureTime != null ? departureTime : LocalDateTime.now());
        return congestionRepository
                .findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
                        targetType, targetId, slot.dowType(), slot.timeSlot())
                .map(this::toResponse)
                .orElse(null);
    }

    private CongestionResponse toResponse(Congestion congestion) {
        return new CongestionResponse(
                congestion.getId().getTargetType(),
                congestion.getId().getTargetId(),
                congestion.getId().getDowType(),
                congestion.getId().getTimeSlot(),
                congestion.getLevel(),
                congestion.getSource(),
                congestion.getUpdatedAt());
    }
}
