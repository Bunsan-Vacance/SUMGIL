<#
.SYNOPSIS
    AI 팀 로컬 Google Drive(SUMGIL) 데이터 동기화.

.DESCRIPTION
    Pull(기본): Drive의 data/ -> 로컬 AI/data/. develop-AI 브랜치의 post-merge 훅이 호출한다.
    Push:       로컬 AI/data/ -> Drive의 data/. 자동 훅에서는 호출되지 않으며, 새로 만든
                데이터를 팀과 공유할 때 수동으로만 실행한다.

    두 방향 모두 원본이 대상보다 오래됐으면 덮어쓰지 않고(robocopy /XO), 대상에만 있는
    파일을 지우지도 않는다(미러링 아님) — 로컬 작업 중인 파일이나 Drive의 다른 팀원 변경을
    실수로 덮어쓰지 않기 위해서다.

.PARAMETER Direction
    Pull(기본) 또는 Push.

.PARAMETER WhatIf
    실제로 복사하지 않고 대상 목록만 출력한다(robocopy /L).
#>
[CmdletBinding()]
param(
    [ValidateSet('Pull', 'Push')]
    [string]$Direction = 'Pull',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

$repoRoot = (& git rev-parse --show-toplevel).Trim()
$configPath = Join-Path $repoRoot 'AI/scripts/.drive-sync-path.local'
$localData = Join-Path $repoRoot 'AI/data'

if (-not (Test-Path $configPath)) {
    Write-Warning "Drive 경로 설정이 없습니다. 먼저 AI/scripts/install_drive_sync_hook.ps1 을 실행하세요."
    exit 0
}

$drivePath = (Get-Content $configPath -Raw).Trim()
$driveData = Join-Path $drivePath 'data'

if (-not (Test-Path $driveData)) {
    Write-Warning "Drive 마운트 경로를 찾을 수 없습니다: $driveData (Google Drive for Desktop이 켜져 있고 로그인돼 있는지 확인하세요)"
    exit 0
}

if ($Direction -eq 'Pull') {
    $source = $driveData
    $dest = $localData
} else {
    $source = $localData
    $dest = $driveData
    if (-not $WhatIf) {
        $confirm = Read-Host "로컬 AI/data/ 의 변경 사항을 팀 공유 Drive로 업로드합니다. 계속할까요? (y/N)"
        if ($confirm -ne 'y') {
            Write-Host '취소했습니다.'
            exit 0
        }
    }
}

$robocopyArgs = @($source, $dest, '/E', '/XO', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NP')
if ($WhatIf) {
    $robocopyArgs += '/L'
}

Write-Host "[$Direction] $source -> $dest"
robocopy @robocopyArgs
$code = $LASTEXITCODE

# robocopy 종료 코드: 0-7 = 성공(일부는 복사 없음/스킵 포함), 8 이상 = 오류
if ($code -ge 8) {
    Write-Warning "robocopy 종료 코드 $code — 일부 복사가 실패했을 수 있습니다."
} else {
    Write-Host "동기화 완료 (robocopy 종료 코드 $code)"
}
