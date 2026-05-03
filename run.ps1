# DABEE_RUN dev server
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  DABEE_RUN dev server" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan

# 기존 :8000 LISTEN 프로세스만 종료 (PID 0 / TIME_WAIT 제외)
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn -and $conn.OwningProcess -gt 4) {
    Write-Host "기존 :8000 프로세스 종료 (PID=$($conn.OwningProcess))..." -ForegroundColor Yellow
    try {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop
        Start-Sleep -Seconds 1
        Write-Host "  ✅ 종료 완료" -ForegroundColor Green
    } catch {
        Write-Host "  ⚠️ 종료 실패: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  → 그냥 새로 시도합니다 (uvicorn이 충돌하면 다른 포트로 변경)" -ForegroundColor Yellow
    }
} else {
    Write-Host ":8000 LISTEN 프로세스 없음 — 바로 시작" -ForegroundColor Gray
}

# venv 활성화
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    & ".\.venv\Scripts\Activate.ps1"
} else {
    Write-Host "⚠️ .venv 없음 — 시스템 Python 사용" -ForegroundColor Yellow
}

Write-Host "`n실행 중: http://127.0.0.1:8000/admin/login" -ForegroundColor Green
Write-Host "종료: Ctrl+C`n" -ForegroundColor Gray
uvicorn app.main:app --reload --port 8000
