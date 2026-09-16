package com.ssafy.s15p21a104.domain.route.repository;

import com.ssafy.s15p21a104.domain.route.entity.RailLinkGeometry;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface RailLinkGeometryRepository extends JpaRepository<RailLinkGeometry, String> {

    /** 매칭(Phase 3)에서 노선 하나의 KTDB link만 추려 작은 그래프를 만들 때 쓴다. */
    List<RailLinkGeometry> findByLineId(String lineId);
}
