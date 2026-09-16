package com.ssafy.s15p21a104.domain.station.repository;

import com.ssafy.s15p21a104.domain.station.entity.TransferMeta;
import com.ssafy.s15p21a104.domain.station.entity.TransferMetaId;
import org.springframework.data.jpa.repository.JpaRepository;

/**
 * {@code transfer_meta} 조회 계약. 환승 실측 시간 공급.
 *
 * <p>행 수가 적어(200행 미만) 기동 시 전건 로드해 메모리에서 조회한다.
 * 기존 엔티티·스키마는 손대지 않으며 추가로 정의하는 신규 인터페이스이다.
 */
public interface TransferMetaRepository extends JpaRepository<TransferMeta, TransferMetaId> {
}
