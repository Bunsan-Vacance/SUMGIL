package com.ssafy.s15p21a104.domain.bus.repository;

import com.ssafy.s15p21a104.domain.bus.entity.BusRoute;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BusRouteRepository extends JpaRepository<BusRoute, String> {
}
