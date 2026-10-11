import { describe, expect, it } from 'vitest'
import { congestionFeedbackMockRepository } from './congestionFeedback'

describe('혼잡 체감 피드백 목업 전송', () => {
  it('아무 데도 보내지 않고 성공한다', async () => {
    await expect(
      congestionFeedbackMockRepository.submit({
        feedbackId: 'id',
        mode: 'subway',
        reportedGrade: 'NORMAL',
      }),
    ).resolves.toBeUndefined()
  })
})
