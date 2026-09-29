package com.ssafy.s15p21a104.domain.congestion.repository;

import com.ssafy.s15p21a104.domain.congestion.entity.Congestion;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionId;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import java.math.BigDecimal;
import java.util.Collection;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface CongestionRepository extends JpaRepository<Congestion, CongestionId> {

    Optional<Congestion> findById_TargetTypeAndId_TargetIdAndId_DowTypeAndId_TimeSlot(
            CongestionTarget targetType, String targetId, Integer dowType, Integer timeSlot);

    /**
     * 해당 슬롯에 혼잡 가중을 발동시키는 값(&gt; {@code level})이 하나라도 있나 — 혼잡 가중 탐색이
     * 시간 탐색과 달라질 수 있는지 판정용(S15P21A104-216 후속). 가중은 LINE·ROUTE만 읽으므로
     * STATION은 제외한다.
     */
    boolean existsById_TargetTypeInAndId_DowTypeAndId_TimeSlotAndLevelGreaterThan(
            Collection<CongestionTarget> targetTypes, Integer dowType, Integer timeSlot,
            BigDecimal level);
}
