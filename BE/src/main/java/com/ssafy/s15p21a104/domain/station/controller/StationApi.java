package com.ssafy.s15p21a104.domain.station.controller;

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
}
