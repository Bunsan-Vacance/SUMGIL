<#
.SYNOPSIS
    AI 팀원이 1회 실행하는 Drive 동기화 훅 설치 스크립트.

.DESCRIPTION
    Google Drive for Desktop이 마운트한 SUMGIL 폴더 경로를 로컬 설정 파일에 저장하고,
    이 저장소의 git hooks 경로를 .githooks 로 지정한다(레포 로컬 설정, --global 아님 —
    다른 저장소나 팀원에게는 영향 없음).

.PARAMETER Path
    SUMGIL 폴더의 로컬 마운트 경로(예: G:\내 드라이브\SUMGIL). 생략하면 물어본다.
#>
[CmdletBinding()]
param(
    [string]$Path
)

$ErrorActionPreference = 'Stop'
$repoRoot = (& git rev-parse --show-toplevel).Trim()

if (-not $Path) {
    $Path = Read-Host "Google Drive에서 SUMGIL 폴더의 로컬 마운트 경로를 입력하세요 (예: G:\내 드라이브\SUMGIL)"
}
$Path = $Path.Trim().TrimEnd('\')

$dataDir = Join-Path $Path 'data'
if (-not (Test-Path $dataDir)) {
    throw "'$dataDir' 를 찾을 수 없습니다. Google Drive for Desktop이 설치·로그인돼 있고, 입력한 경로가 SUMGIL 폴더가 맞는지 확인하세요."
}

$configPath = Join-Path $repoRoot 'AI/scripts/.drive-sync-path.local'
Set-Content -Path $configPath -Value $Path -NoNewline -Encoding utf8

git -C $repoRoot config --local core.hooksPath .githooks

Write-Host "설정 완료"
Write-Host "  Drive 경로: $Path"
Write-Host "  git hooks 경로: core.hooksPath = .githooks (이 저장소 로컬 설정)"
Write-Host ""
Write-Host "이제 develop-AI 브랜치에서 git pull 로 새 MR을 받을 때마다 AI/data/ 가 Drive 최신 데이터로 자동 업데이트됩니다."
Write-Host "새로 만든 데이터를 Drive에 올릴 때는 수동으로 실행하세요: powershell AI/scripts/sync_drive_data.ps1 -Direction Push"
