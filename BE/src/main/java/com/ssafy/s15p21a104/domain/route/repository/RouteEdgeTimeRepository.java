package com.ssafy.s15p21a104.domain.route.repository;

import com.ssafy.s15p21a104.domain.route.entity.EdgeTime;
import com.ssafy.s15p21a104.domain.route.entity.EdgeTimeId;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

/**
 * {@code edge_time} 조회 계약. 그래프 로드용 데이터 공급.
 *
 * <p>SUBWAY 행을 대표 슬롯 1개({@code dowType}·{@code timeSlot})로 필터해
 * 조립 로더의 입력인 {@link RouteEdgeRow} 목록으로 돌려준다.
 * PK가 (from, to, mode, route, dow, slot)이므로 대표 슬롯 안에서는
 * 출발·도착·노선 조합에 중복이 발생하지 않는다.
 *
 * <p>역 이름은 기존 {@code StationRepository}({@code station_id} 조회)를 재사용하고,
 * 노선 이름은 {@link RouteLineRepository}를 사용한다.
 * 기존 엔티티·스키마는 손대지 않으며 추가로 정의하는 신규 인터페이스이다.
 */
public interface RouteEdgeTimeRepository extends JpaRepository<EdgeTime, EdgeTimeId> {

    /**
     * 대표 슬롯 1개의 SUBWAY 구간 행을 조립 입력 형태로 조회한다.
     *
     * @param dowType 대표 슬롯 dow_type
     * @param timeSlot 대표 슬롯 time_slot
     * @return SUBWAY 행(SUBWAY 행 0개면 빈 목록)
     */
    @Query("""
            select new com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow(
                e.id.fromNode, e.id.toNode, e.id.routeId, e.travelSec, e.waitSec)
            from EdgeTime e
            where e.id.mode = com.ssafy.s15p21a104.domain.route.entity.TravelMode.SUBWAY
              and e.id.dowType = :dowType and e.id.timeSlot = :timeSlot
            """)
    List<RouteEdgeRow> findSubwayEdgesBySlot(@Param("dowType") int dowType,
                                             @Param("timeSlot") int timeSlot);

    /**
     * 기본(평일 0번 슬롯) 대표 슬롯의 SUBWAY 행을 조회한다.
     *
     * <p>PoC는 dow_type×time_slot 전 슬롯 동일값 전제이므로 어느 슬롯을 읽어도 같다.
     */
    default List<RouteEdgeRow> findSubwayEdgesForDefaultSlot() {
        return findSubwayEdgesBySlot(0, 0);
    }

    /** 역이 속한 SUBWAY 노선 ID 목록(환승역이면 여러 개). 역 검색(stations/search) 결과에 노선 정보를 붙일 때 쓴다. */
    @Query("""
            select distinct e.id.routeId
            from EdgeTime e
            where e.id.mode = com.ssafy.s15p21a104.domain.route.entity.TravelMode.SUBWAY
              and (e.id.fromNode = :stationId or e.id.toNode = :stationId)
            """)
    List<String> findDistinctSubwayRouteIdsByStationId(@Param("stationId") String stationId);
}
