"""DL 아티팩트 로딩 → 예측 재구성(`lookup + z-잔차 × scale`) — 144.

`predict.CrowdPredictor`(LightGBM)와 같은 자리의 시퀀스 모델판이다. 아티팩트 디렉터리 하나를 읽어
패널 형태의 입력(파생 전: 날짜·역·시간대·요일유형·이벤트·승하차)에 대해 승차·하차 예측을 낸다.

## 입력 창과 결측

- 창에는 대상 날짜와 **과거 행**이 함께 들어온다. 과거 행의 잔차(실측 − lookup)가 시퀀스 채널이 되고,
  없는 날은 마스크 0이다. 창이 `seq_days`보다 짧으면(예: 배치 기본 7일) 앞쪽이 통째로 마스크 0 —
  학습 때 이력 절단 증강으로 본 상황이라 그대로 동작한다.
- 대상 날짜 행은 승하차가 NaN이므로 잔차가 만들어지지 않아 자동으로 마스크 0이다(자기 자신을 보지 않는다).
- lookup 조회 실패 행은 `{t}_lookup`·`{t}_pred` 모두 NaN으로 남긴다 — 채우지 않는다(원칙 8).

## 결정적 CPU 추론

torch는 이 모듈 안에서만 import하고, `map_location`은 기본이 `cpu`다 — GPU에서 학습한 아티팩트를
GPU 없는 EC2 배치가 그대로 읽는 경로다(`AI/CLAUDE.md` "딥러닝 학습 — GPU 우선").

## 입력 설계 변형(198)

`meta.json`의 `seq_features`·`use_static_events`로 채널을 복원한다. 키가 없는 144 아티팩트는
`base` + 정적 이벤트로 본다. `neighbor` 아티팩트는 **서빙에서도 이웃 잔차가 필요**하므로
`predict(panel_window, segments)`의 `segments`(= `dataset.resolved_segments` 결과)로 이웃 표를 만들고
창 안의 잔차에 `adjacency.attach_neighbor_features`를 붙인다 — 파생 캐시의 `nb_*_resid`와 같은 계산이다.
창에 `station_name`이 없으면 환승(`xfer`) side는 만들 수 없어 그 채널만 마스크 0이 된다.

`scenario`(`masking.SCENARIOS`)를 주면 이력 마스크에서 지정한 시차만 남긴다 — 144 4단계 평가가
`full / d7_only / d1_only / no_lag`를 **서빙과 같은 코드로** 재려고 쓰는 스위치이고, 운영 기본은 None이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.dl.dataset import (
    EVENT_STATIC_COLS,
    NEIGHBOR_RESID_COLS,
    RESID_COLS,
    SequencePanel,
    scenario_seq,
    seq_channels_for,
    stat_features_for,
)
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline

OUTPUT_KEYS = ["date", "station_no", "time_slot"]


class DLResidualPredictor:
    """아티팩트 디렉터리 하나 = 시퀀스 예측기 하나."""

    def __init__(
        self,
        artifact_dir: Path,
        device: str = "cpu",
        batch_size: int = 512,
        scenario: str | None = None,
    ) -> None:
        import torch

        from app.CROWD.pipeline.dl.model import ResidualGRU

        self.dir = Path(artifact_dir)
        self.meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        self.device = device
        self.batch_size = batch_size
        self.scenario = scenario
        self.seq_days: int = int(self.meta["seq_days"])
        # 198: 옛 아티팩트(144)에는 이 키가 없다 → base · 정적 이벤트 있음
        self.seq_features: str = str(self.meta.get("seq_features", "base"))
        self.use_static_events: bool = bool(self.meta.get("use_static_events", True))
        self.station_ids = np.asarray(self.meta["station_ids"], dtype="int64")
        self.scale = pd.read_parquet(self.dir / "scale.parquet")
        self.event_stats = pd.read_parquet(self.dir / "event_stats.parquet")
        self.lookup = DayTypeLookupBaseline.load(
            self.dir / "lookup.parquet",
            keys=self.meta["lookup_keys"],
            targets=self.meta["targets"],
        )
        self.model = ResidualGRU(
            len(self.station_ids),
            model=self.meta["model"],
            hidden=int(self.meta["hidden"]),
            emb_dim=int(self.meta.get("emb_dim", 16)),
            mlp_hidden=int(self.meta.get("mlp_hidden", 128)),
            seq_channels=seq_channels_for(self.seq_features),
            stat_features=stat_features_for(self.use_static_events),
        )
        state = torch.load(self.dir / "model.pt", map_location=device)
        self.model.load_state_dict(state)
        self.model.to(device).eval()

    # ── 입력 준비 ──
    def _frame(
        self, panel_window: pd.DataFrame, neighbor_map: pd.DataFrame | None = None
    ) -> pd.DataFrame:
        """패널 창 → SequencePanel이 먹는 파생 프레임(잔차·요일유형·이벤트[·이웃 잔차])."""
        cols = ["date", "station_no", "time_slot", "day_type"]
        out = panel_window[cols].copy()
        out["date"] = pd.to_datetime(out["date"]).dt.normalize()
        resid = self.lookup.residuals(panel_window)
        for c in RESID_COLS:
            out[c] = resid[c].to_numpy()
        for c in EVENT_STATIC_COLS:
            if c in panel_window.columns:
                out[c] = panel_window[c].to_numpy()
        if self.seq_features == "neighbor":
            from app.CROWD.pipeline.adjacency import attach_neighbor_features

            # 파생 캐시의 `nb_*_resid`와 같은 계산(같은 date·time_slot, 이웃 여럿이면 평균)
            out = attach_neighbor_features(out, neighbor_map, RESID_COLS)
            for c in NEIGHBOR_RESID_COLS:  # 이웃 표에 없는 side는 NaN → 그 side 마스크 0
                if c not in out.columns:
                    out[c] = np.nan
        return out

    def _neighbor_map(self, panel_window: pd.DataFrame, segments) -> pd.DataFrame:
        """`neighbor` 안의 서빙 경로 — 세그먼트에서 노선 앞뒤, 역명에서 환승 이웃 표를 만든다."""
        from app.CROWD.pipeline.adjacency import build_neighbor_map, build_transfer_map

        line_map = build_neighbor_map(segments or [])
        maps = [line_map]
        if "station_name" in panel_window.columns:
            nodes = panel_window[
                ["station_no", "station_name"]
                + (["line"] if "line" in panel_window.columns else [])
            ].drop_duplicates("station_no")
            maps.append(build_transfer_map(nodes))
        out = pd.concat(maps, ignore_index=True)
        if not len(out):
            raise ValueError(
                "seq_features='neighbor' 아티팩트는 이웃 표가 필요하다 — predict(segments=…)에 "
                "resolved_segments 결과를 넘겨라(빈 목록·역명 없는 창은 이웃을 만들 수 없다)."
            )
        return out

    def _sample_index(
        self, sp: SequencePanel, frame: pd.DataFrame
    ) -> tuple[np.ndarray, np.ndarray]:
        """창 안에 **행이 존재하는** 모든 (역, 날짜) 쌍. 실측 유무와 무관하다(대상 날짜가 여기 든다)."""
        pairs = frame[["station_no", "date"]].drop_duplicates()
        pairs = pairs[pairs["station_no"].isin(sp.station_ids)]
        s_lookup = pd.Series(np.arange(len(sp.station_ids)), index=sp.station_ids)
        s_idx = s_lookup.loc[pairs["station_no"]].to_numpy()
        d_idx = (pd.DatetimeIndex(pairs["date"]) - sp.dates[0]).days.to_numpy()
        return s_idx.astype("int64"), d_idx.astype("int64")

    # ── 예측 ──
    def predict_resid(
        self, panel_window: pd.DataFrame, segments: list[dict] | None = None
    ) -> pd.DataFrame:
        """창 전체의 (역, 날짜) × 20슬롯 잔차 예측(명 단위) 롱 프레임."""
        import torch

        neighbor_map = (
            self._neighbor_map(panel_window, segments) if self.seq_features == "neighbor" else None
        )
        frame = self._frame(panel_window, neighbor_map)
        sp = SequencePanel.build(
            frame,
            self.scale,
            self.event_stats,
            station_ids=self.station_ids,
            seq_features=self.seq_features,
            use_static_events=self.use_static_events,
            neighbor_map=neighbor_map,
        )
        s_idx, d_idx = self._sample_index(sp, frame)
        if not len(s_idx):
            return pd.DataFrame(
                columns=["station_no", "date", "time_slot", *[f"{t}_resid_pred" for t in TARGETS]]
            )
        chunks = []
        with torch.no_grad():
            for start in range(0, len(s_idx), self.batch_size):
                sl = slice(start, start + self.batch_size)
                batch = sp.make_batch(s_idx[sl], d_idx[sl], self.seq_days)
                x_seq = batch["x_seq"]
                if self.scenario is not None:
                    x_seq = scenario_seq(x_seq, self.scenario, self.seq_features)
                z = self.model(
                    torch.from_numpy(x_seq).to(self.device),
                    torch.from_numpy(batch["x_stat"]).to(self.device),
                    torch.from_numpy(batch["station"]).to(self.device),
                )
                resid = sp.inverse(z.cpu().numpy(), s_idx[sl])
                chunks.append(sp.to_frame(s_idx[sl], d_idx[sl], resid))
        return pd.concat(chunks, ignore_index=True)

    def predict(
        self, panel_window: pd.DataFrame, segments: list[dict] | None = None
    ) -> pd.DataFrame:
        """`Predictor` 계약: 입력 행마다 한 행(OUTPUT_KEYS + `{t}_pred` + `{t}_lookup`)."""
        resid_pred = self.predict_resid(panel_window, segments)
        out = panel_window[OUTPUT_KEYS].copy()
        out["date"] = pd.to_datetime(out["date"]).dt.normalize()
        lookup_pred = self.lookup.predict(panel_window)
        merged = out.merge(resid_pred, on=OUTPUT_KEYS, how="left")
        for t in TARGETS:
            lk = lookup_pred[t].to_numpy(dtype="float64")
            # 아티팩트에 없는 역은 잔차를 못 내므로 lookup만 쓴다(잔차 0) — 273역 패널에서는 나오지 않는다.
            resid = np.nan_to_num(merged[f"{t}_resid_pred"].to_numpy(dtype="float64"), nan=0.0)
            out[f"{t}_lookup"] = lk
            out[f"{t}_pred"] = lk + resid  # lookup이 NaN이면 예측도 NaN(채우지 않는다)
        return out
