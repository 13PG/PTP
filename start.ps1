$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
$appUrl = "http://127.0.0.1:5050"

function Test-AppReady {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-AppReady {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-AppReady -Url $Url) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

try {
    if (Test-AppReady -Url $appUrl) {
        Start-Process $appUrl | Out-Null
        exit 0
    }

    if (-not (Test-Path $python)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败。" }
        & $python -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "安装依赖失败。" }
    }

    & $python -c "import flask, fitz, docx, pptx, PIL, jieba, rapidocr_onnxruntime" *> $null
    if ($LASTEXITCODE -ne 0) {
        & $python -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "更新依赖失败。" }
    }

    $serverCommand = "Set-Location '$root'; & '$python' app.py"
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $serverCommand) -WindowStyle Normal | Out-Null

    if (-not (Wait-AppReady -Url $appUrl -TimeoutSeconds 30)) {
        throw "服务启动超时。请查看服务窗口里的报错信息。"
    }

    Start-Process $appUrl | Out-Null
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "按回车键关闭"
    exit 1
}
