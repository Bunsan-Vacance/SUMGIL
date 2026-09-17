// AI EC2 의 재고 예측 산출물 중 최신 것을 고르는 규칙.
// 실행: node --test "BE/scripts/data/test/*.test.mjs"
//
// 최신 판정은 파일명 정렬이다. 배치가 이름에 생성시각(YYYYMMDD-HHMMSS)을 넣으므로 사전순 = 시간순이고,
// AI 서빙 API 도 같은 규칙으로 최신 파일을 고른다(AI/app/BIKE/service.py 의 sorted(glob)).
// 자바 로더(CsvBikeStockPredSource)도 같다 — 세 곳이 "최신" 을 다르게 고르면 서로 다른 표를 본다.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { ARTIFACT_PATTERN, latestArtifact, siblingMeta } from '../lib/bikepred-fetch.mjs';

describe('latestArtifact', () => {
  test('파일명이 가장 늦은 산출물을 고른다', () => {
    const names = [
      'bike_stock_pred_20260915-003838.csv',
      'bike_stock_pred_20260917-014432.csv',
      'bike_stock_pred_20260917-004419.csv',
    ];

    assert.equal(latestArtifact(names), 'bike_stock_pred_20260917-014432.csv');
  });

  test('같은 날짜면 시각으로 가른다', () => {
    const names = ['bike_stock_pred_20260917-004201.csv', 'bike_stock_pred_20260917-004419.csv'];

    assert.equal(latestArtifact(names), 'bike_stock_pred_20260917-004419.csv');
  });

  test('parquet·meta.json 은 고르지 않는다 — 같은 폴더에 함께 있다', () => {
    const names = [
      'bike_stock_pred_20260918-999999.parquet',
      'bike_stock_pred_20260918-999999.meta.json',
      'bike_stock_pred_20260917-014432.csv',
    ];

    assert.equal(latestArtifact(names), 'bike_stock_pred_20260917-014432.csv');
  });

  test('이름 규칙에 맞지 않는 파일은 무시한다', () => {
    const names = ['README.md', 'bike_stock_pred.csv', 'other_20260917-014432.csv'];

    assert.equal(latestArtifact(names), null);
  });

  test('빈 목록이면 null 이다 — 부르는 쪽이 경로를 담아 오류를 낸다', () => {
    assert.equal(latestArtifact([]), null);
  });
});

describe('siblingMeta', () => {
  test('CSV 이름에서 meta.json 이름을 만든다', () => {
    assert.equal(siblingMeta('bike_stock_pred_20260917-014432.csv'), 'bike_stock_pred_20260917-014432.meta.json');
  });
});

describe('ARTIFACT_PATTERN', () => {
  test('생성시각이 붙은 CSV 만 매치한다', () => {
    assert.ok(ARTIFACT_PATTERN.test('bike_stock_pred_20260917-014432.csv'));
    assert.ok(!ARTIFACT_PATTERN.test('bike_stock_pred_20260917-014432.parquet'));
    assert.ok(!ARTIFACT_PATTERN.test('bike_stock_pred_20260917-014432.meta.json'));
  });
});
