package com.ssafy.s15p21a104.domain.boarding.service;

import com.ssafy.s15p21a104.domain.boarding.dto.request.BoardingRequest;
import com.ssafy.s15p21a104.domain.boarding.dto.response.BoardingResponse;
import com.ssafy.s15p21a104.domain.boarding.entity.BoardingEvent;
import com.ssafy.s15p21a104.domain.boarding.repository.BoardingEventRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class BoardingService {

    private final BoardingEventRepository boardingEventRepository;

    @Transactional
    public BoardingResponse record(BoardingRequest request) {
        validate(request);
        BoardingEvent event = BoardingEvent.of(
                request.mode(), request.fromNodeId(), request.fromNodeName(),
                request.toNodeId(), request.toNodeName(),
                request.routeId(), request.routeName(),
                request.status(), request.departureTime(), request.reportedAt());
        return BoardingResponse.from(boardingEventRepository.save(event));
    }

    private void validate(BoardingRequest request) {
        if (request == null || request.mode() == null || request.status() == null
                || request.reportedAt() == null) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
        if (isBlank(request.fromNodeId()) || isBlank(request.toNodeId())) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
