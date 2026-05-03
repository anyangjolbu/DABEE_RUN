# DABEE_RUN 서버 실행
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  DABEE_RUN dev server" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan

# 기존 :8000 점유 프로세스 자동 종료
$conn = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Write-Host "기존 :8000 프로세스 종료 (PID=$($conn.OwningProcess))..." -ForegroundColor Yellow
    Stop-Process -Id $conn.OwningProcess -Force
    Start-Sleep -Seconds 1
}

# venv 활성화
& ".\.venv\Scripts\Activate.ps1"

Write-Host "`n실행 중: http://127.0.0.1:8000/admin/login" -ForegroundColor Green
Write-Host "종료: Ctrl+C`n" -ForegroundColor Gray
uvicorn app.main:app --reload --port 8000
