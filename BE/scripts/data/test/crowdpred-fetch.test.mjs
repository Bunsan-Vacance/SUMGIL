// AI EC2 의 혼잡도 예측 산출물 중 내려받을 것을 고르는 규칙.
// 실행: node --test "BE/scripts/data/test/*.test.mjs"
//
// 이 스크립트는 "최신" 을 고르지 않는다 — 대상 날짜가 기준일 이후인 산출물을 전부 받아 폴더를 동기화한다.
// 같은 날짜의 최신 회차를 고르는 일은 자바 로더(CsvCongestionPredSource) 가 사이드카 generated_at 으로
// 한다. 규칙을 한 곳에만 두기 위해서다(304). 파일명 _HHMMSS 는 생성 시각만 있고 생성 날짜가 없어
// 같은 대상 날짜의 두 회차(전날 "내일치" · 당일 "오늘치")를 이름으로는 가를 수 없다.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { ARTIFACT_PATTERN, artifactsSince, siblingMeta } from '../lib/crowdpred-fetch.mjs';

describe('artifactsSince', () => {
  test('오늘·내일 2일치를 모두 고른다 — 배치가 한 번에 날짜가 다른 파일 둘을 만든다', () => {
    const names = [
      'predictions_2026-09-22_063114.csv',
      'predictions_2026-09-21_063113.csv',
    ];

    assert.deepEqual(artifactsSince(names, '2026-09-21'), [
      'predictions_2026-09-21_063113.csv',
      'predictions_2026-09-22_063114.csv',
    ]);
  });

  test('기준일보다 앞선 날짜는 건너뛴다 — 조회가 오늘 날짜로만 하므로 과거는 받지 않는다', () => {
    const names = [
      'predictions_2026-09-20_093000.csv',
      'predictions_2026-09-21_063113.csv',
      'predictions_2026-09-22_063114.csv',
    ];

    assert.deepEqual(artifactsSince(names, '2026-09-21'), [
      'predictions_2026-09-21_063113.csv',
      'predictions_2026-09-22_063114.csv',
    ]);
  });

  test('같은 날짜의 여러 회차를 전부 고른다 — 최신 판정은 자바 로더가 generated_at 으로 한다', () => {
    const names = [
      'predictions_2026-09-23_003400.csv',
      'predictions_2026-09-23_003100.csv',
    ];

    assert.deepEqual(artifactsSince(names, '2026-09-23'), [
      'predictions_2026-09-23_003100.csv',
      'predictions_2026-09-23_003400.csv',
    ]);
  });

  test('기준일이 없으면 전부 고른다', () => {
    const names = ['predictions_2026-09-20_093000.csv', 'predictions_2026-09-21_063113.csv'];

    assert.deepEqual(artifactsSince(names), names);
  });

  test('사이드카·parquet 은 고르지 않는다 — 같은 폴더에 함께 있다', () => {
    const names = [
      'predictions_2026-09-21_063113.csv',
      'predictions_2026-09-21_063113.meta.json',
      'predictions_2026-09-21.meta.json',
      'predictions_2026-09-21.parquet',
      'predictions_link_2026-09-21.parquet',
    ];

    assert.deepEqual(artifactsSince(names, '2026-09-21'), ['predictions_2026-09-21_063113.csv']);
  });

  test('학습용·재고 예측 등 다른 산출물은 고르지 않는다', () => {
    const names = [
      'predictions_train_2026-09-21_235959.csv',
      'bike_stock_pred_20260917-014432.csv',
      'predictions_2026-09-21_063113.csv',
    ];

    assert.deepEqual(artifactsSince(names, '2026-09-21'), ['predictions_2026-09-21_063113.csv']);
  });

  test('후보가 없으면 빈 배열', () => {
    assert.deepEqual(artifactsSince([], '2026-09-21'), []);
    assert.deepEqual(artifactsSince(['README.md'], '2026-09-21'), []);
    assert.deepEqual(artifactsSince(['predictions_2026-09-20_093000.csv'], '2026-09-21'), []);
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
