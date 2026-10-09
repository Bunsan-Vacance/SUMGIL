package com.ssafy.s15p21a104.domain.station.controller;

import com.ssafy.s15p21a104.domain.station.dto.response.StationNearbyResponse;
import com.ssafy.s15p21a104.domain.station.dto.response.StationSearchResultResponse;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.List;

@Tag(name = "역")
@RequestMapping("/api/stations")
public interface StationApi {

    @Operation(summary = "역 검색", description = "이름으로 역을 검색해 BE 정식 역 ID(역번호)를 반환한다. "
            + "routes/search의 originStationId/destStationId에 그대로 쓸 수 있다.")
    @GetMapping("/search")
    ApiResult<List<StationSearchResultResponse>> search(@RequestParam String query);

    @Operation(summary = "근처 역 조회", description = "좌표 기준 반경 안의 역을 거리순으로 반환한다. "
            + "물리 역 1행에 소속 노선 배열(lines)을 담으며 노선이 없으면 빈 배열이다. "
            + "기본 반경 1000m(최대 3000m), 기본 20개(최대 50개). "
            + "좌표 오류는 400 INVALID_COORDINATE, 반경·개수가 범위 밖이면 400 BAD_REQUEST, "
            + "결과가 없으면 200 빈 배열이다. "
            + "stationId는 불투명 문자열이며 congestion/batch·routes/search에 그대로 쓴다.")
    @GetMapping("/nearby")
    ApiResult<List<StationNearbyResponse>> nearby(
            @RequestParam Double lat,
            @RequestParam Double lng,
            @RequestParam(required = false) Integer radiusMeters,
            @RequestParam(required = false) Integer limit
    );
}
