package com.ssafy.s15p21a104.domain.boarding.dto.response;

import com.ssafy.s15p21a104.domain.boarding.entity.BoardingEvent;
import com.ssafy.s15p21a104.domain.boarding.entity.BoardingStatus;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.time.OffsetDateTime;

public record BoardingResponse(
        Long id,
        TravelMode mode,
        String fromNodeId,
        String fromNodeName,
        String toNodeId,
        String toNodeName,
        String routeId,
        String routeName,
        BoardingStatus status,
        String departureTime,
        OffsetDateTime reportedAt
) {
    public static BoardingResponse from(BoardingEvent event) {
        return new BoardingResponse(
                event.getId(), event.getMode(),
                event.getFromNodeId(), event.getFromNodeName(),
                event.getToNodeId(), event.getToNodeName(),
                event.getRouteId(), event.getRouteName(),
                event.getStatus(), event.getDepartureTime(), event.getReportedAt());
    }
}
