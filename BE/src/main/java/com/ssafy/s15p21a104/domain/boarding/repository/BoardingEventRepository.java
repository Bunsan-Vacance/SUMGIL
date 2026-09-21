package com.ssafy.s15p21a104.domain.boarding.repository;

import com.ssafy.s15p21a104.domain.boarding.entity.BoardingEvent;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BoardingEventRepository extends JpaRepository<BoardingEvent, Long> {
}
