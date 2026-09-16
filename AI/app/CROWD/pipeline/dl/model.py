"""잔차 시퀀스 모델 — 하루(20슬롯) 형태를 한 번에 내는 RNN(144).

LightGBM 배포 세트는 **셀 하나(역, 날짜, 슬롯)**를 독립 행으로 보고 시차 6열을 피처로 받는다.
그래서 "이력이 며칠 있는가"가 피처 결측으로만 표현되고, 학습에서 본 적 없는 결측 패턴이 들어오면
lookup보다 −37%까지 떨어진다(143). 시퀀스 모델은 이력 길이를 **마스크 채널**로 명시적으로 받으므로
"이력이 짧다"가 학습 분포 안에 들어온다 — 144가 재려는 것이 정확히 이 차이다.

```
x_seq  [B, N, 20, 7]  → flatten(20×7=140) → GRU/LSTM(hidden) → h_N  [B, hidden]
x_stat [B, 9] + 역 임베딩 [B, 16]
h_N ⊕ emb ⊕ x_stat → Linear(128) → ReLU → Linear(40) → [B, 20, 2] z-잔차
```

- 하루를 한 표본으로 두고 20슬롯을 **한 번에** 내는 이유: 아침·저녁 첨두의 모양이 그 날 전체에
  걸쳐 같이 움직이므로(휴일·행사) 슬롯별 독립 예측보다 정보가 많다. 출력 20×2는 `y_mask`로
  가려 손실을 계산한다 — 실측이 없는 슬롯에 값을 맞추라고 시키지 않는다(원칙 8).
- 역 임베딩(273→16): 잔차 규모는 z-정규화로 이미 없앴지만 "역의 성격"(업무지구·주거지)은 남는다.
- `--model lstm`은 게이트 구조만 바꾼 대조군이다. 두 계열 모두 마지막 은닉 상태만 쓴다.

torch는 이 모듈에서 최상단 import한다 — `pipeline/dl/`은 학습·추론 전용이고 서빙 경로
(`router.py`/`service.py`/`predictor.py`)는 이 모듈을 지연 import한다(`AI/CLAUDE.md`).
"""

from __future__ import annotations

import torch
from torch import nn

from app.CROWD.pipeline.dl.dataset import N_SLOTS, N_TARGETS, SEQ_CHANNELS, STAT_FEATURES

RNN_KINDS = {"gru": nn.GRU, "lstm": nn.LSTM}


class ResidualGRU(nn.Module):
    """이력 시퀀스 + 정적 피처 → 대상일 20슬롯 z-잔차. `model="lstm"`이면 셀만 LSTM으로 바뀐다."""

    def __init__(
        self,
        n_stations: int,
        model: str = "gru",
        hidden: int = 64,
        emb_dim: int = 16,
        mlp_hidden: int = 128,
        seq_channels: int = SEQ_CHANNELS,
        stat_features: int = STAT_FEATURES,
        n_slots: int = N_SLOTS,
        n_targets: int = N_TARGETS,
    ) -> None:
        super().__init__()
        if model not in RNN_KINDS:
            raise ValueError(f"모르는 모델 {model!r} — {sorted(RNN_KINDS)} 중 하나")
        self.model = model
        self.n_slots = n_slots
        self.n_targets = n_targets
        self.embedding = nn.Embedding(n_stations, emb_dim)
        self.rnn = RNN_KINDS[model](
            input_size=n_slots * seq_channels, hidden_size=hidden, num_layers=1, batch_first=True
        )
        self.head = nn.Sequential(
            nn.Linear(hidden + emb_dim + stat_features, mlp_hidden),
            nn.ReLU(),
            nn.Linear(mlp_hidden, n_slots * n_targets),
        )

    def forward(
        self, x_seq: torch.Tensor, x_stat: torch.Tensor, station: torch.Tensor
    ) -> torch.Tensor:
        b, n = x_seq.shape[0], x_seq.shape[1]
        out, _ = self.rnn(x_seq.reshape(b, n, -1))
        h = out[:, -1]  # 마지막 은닉 상태 = D−1까지 본 요약
        z = torch.cat([h, self.embedding(station), x_stat], dim=-1)
        return self.head(z).reshape(b, self.n_slots, self.n_targets)


def masked_huber(
    pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor, delta: float = 1.0
) -> torch.Tensor:
    """실측이 있는 슬롯(`mask`=1)만 평균낸 Huber 손실(z 단위).

    RMSE·MAE 둘 다 145 판정 지표라 한쪽에 치우친 MSE/L1 대신 Huber를 쓴다. 마스크 합이 0인 배치는
    0을 돌려준다(학습 중 나올 수 없지만 방어).
    """
    w = mask.unsqueeze(-1).expand_as(pred)
    loss = nn.functional.huber_loss(pred, target, reduction="none", delta=delta)
    denom = w.sum()
    if denom == 0:
        return loss.sum() * 0.0
    return (loss * w).sum() / denom
