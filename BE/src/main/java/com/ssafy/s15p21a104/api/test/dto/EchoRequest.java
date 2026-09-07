package com.ssafy.s15p21a104.api.test.dto;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class EchoRequest {

    @NotBlank(message = "name은 비어 있을 수 없습니다.")
    private String name = "world";

    @Min(value = 1, message = "count는 1 이상이어야 합니다.")
    private int count = 1;
}
