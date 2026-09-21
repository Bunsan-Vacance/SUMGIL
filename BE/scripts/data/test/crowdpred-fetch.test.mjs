// AI EC2 의 혼잡도 예측 산출물 중 최신 것을 고르는 규칙.
// 실행: node --test "BE/scripts/data/test/*.test.mjs"
//
// 최신 판정은 파일명 정렬이다. 배치가 이름에 대상 날짜와 생성시각을 넣으므로 사전순 = 시간순이고,
// 자바 로더(CsvCongestionPredSource)도 같은 규칙을 쓴다 — 두 곳이 다르게 고르면 받은 파일과
// 적재한 파일이 달라진다.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { ARTIFACT_PATTERN, latestArtifact, siblingMeta } from '../lib/crowdpred-fetch.mjs';

describe('latestArtifact', () => {
  test('파일명이 가장 늦은 산출물을 고른다', () => {
    const names = [
      'predictions_2026-09-19_101500.csv',
      'predictions_2026-09-20_234300.csv',
      'predictions_2026-09-20_093000.csv',
    ];

    assert.equal(latestArtifact(names), 'predictions_2026-09-20_234300.csv');
  });

  test('같은 날짜면 생성시각으로 가른다 — 재생성분이 쌓인다', () => {
    const names = ['predictions_2026-09-20_093000.csv', 'predictions_2026-09-20_234300.csv'];

    assert.equal(latestArtifact(names), 'predictions_2026-09-20_234300.csv');
  });

  test('사이드카·parquet 은 고르지 않는다 — 같은 폴더에 함께 있다', () => {
    const names = [
      'predictions_2026-09-20_234300.csv',
      'predictions_2026-09-20_234300.meta.json',
      'predictions_link_2026-09-20.parquet',
      'predictions_2026-09-20.meta.json',
    ];

    assert.equal(latestArtifact(names), 'predictions_2026-09-20_234300.csv');
  });

  test('학습용 등 다른 산출물은 고르지 않는다', () => {
    const names = ['predictions_train_2026-09-20_235959.csv', 'predictions_2026-09-20_093000.csv'];

    assert.equal(latestArtifact(names), 'predictions_2026-09-20_093000.csv');
  });

  test('재고 예측 산출물은 고르지 않는다 — 다른 배치다', () => {
    assert.equal(latestArtifact(['bike_stock_pred_20260917-014432.csv']), null);
  });

  test('후보가 없으면 null', () => {
    assert.equal(latestArtifact([]), null);
    assert.equal(latestArtifact(['README.md']), null);
  });
});

describe('ARTIFACT_PATTERN', () => {
  test('날짜에 하이픈이 있고 시각이 6자리여야 한다', () => {
    assert.ok(ARTIFACT_PATTERN.test('predictions_2026-09-20_234300.csv'));
    assert.ok(!ARTIFACT_PATTERN.test('predictions_20260920_234300.csv'));
    assert.ok(!ARTIFACT_PATTERN.test('predictions_2026-09-20_2343.csv'));
    assert.ok(!ARTIFACT_PATTERN.test('predictions_2026-09-20.csv'));
  });
});

describe('siblingMeta', () => {
  test('같은 회차의 사이드카 이름을 만든다', () => {
    assert.equal(
      siblingMeta('predictions_2026-09-20_234300.csv'),
      'predictions_2026-09-20_234300.meta.json',
    );
  });
});
