package com.ssafy.s15p21a104.domain.route.repository;

import com.ssafy.s15p21a104.domain.station.entity.Line;
import org.springframework.data.jpa.repository.JpaRepository;

/**
 * {@code line} 노선 이름 조회 계약. 그래프 로드·이름 매핑용.
 *
 * <p>역 이름은 기존 {@code StationRepository}({@code station_id} 조회)를 재사용한다.
 * 기존 엔티티·스키마는 손대지 않으며 추가로 정의하는 신규 인터페이스이다.
 */
public interface RouteLineRepository extends JpaRepository<Line, String> {
}
