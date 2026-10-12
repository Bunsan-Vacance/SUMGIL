import type { SegmentCongestionGrade } from '../features/route/types'

export type FeedbackGrade = 'RELAXED' | 'NORMAL' | 'CONGESTED'

export interface CongestionFeedbackRequest {
  // 클라이언트 생성 ID. BE 중복 방지 기준 후보다.
  feedbackId: string
  mode: 'subway' | 'bus'
  routeId?: string
  fromStationId?: string
  fromName?: string
  toStationId?: string
  toName?: string
  // 추정 탑승 시각(ISO)
  boardedAt?: string
  reportedGrade: FeedbackGrade
  predictedGrade?: SegmentCongestionGrade
}

export interface CongestionFeedbackRepository {
  submit(request: CongestionFeedbackRequest, signal?: AbortSignal): Promise<void>
}

// BE 355 계약이 정해지기 전까지 아무 데도 보내지 않는다.
export const congestionFeedbackMockRepository: CongestionFeedbackRepository = {
  submit: async () => undefined,
}

// 355 합의 후 실제 repository로 교체한다.
export const congestionFeedbackRepository: CongestionFeedbackRepository =
  congestionFeedbackMockRepository
