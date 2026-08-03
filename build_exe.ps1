# ============================================================
# pad_webdriver_ref.exe をビルドする（Windows 専用）
#   PyInstaller はクロスコンパイルできないので、Windows 上で実行すること。
#   管理者ではない PowerShell から動かす。
# ============================================================
param(
    [ValidateSet("onefile", "onedir")]
    [string]$Mode = "onefile"
)

$ErrorActionPreference = "Stop"

# 変換に要らないものを明示的に外す。指定しないと PyInstaller が
# browser_factory の遅延 import まで静的に追いかけ、selenium と
# playwright を丸ごと同梱して 80MB 近くまで膨らむ。
$excludes = @(
    "browser", "browser_playwright", "browser_factory",
    "run_batch", "run_recording", "agent", "agent_core", "agent_ollama",
    "selenium", "playwright", "openpyxl",
    "tkinter", "unittest", "pydoc", "setuptools", "pkg_resources",
    "win32com", "pythoncom", "win32api", "pywin32"
)
$args = @("--$Mode", "--console", "--name", "pad_webdriver_ref", "--noconfirm")
foreach ($m in $excludes) { $args += @("--exclude-module", $m) }
$args += "pad_webdriver_ref.py"

pyinstaller @args

$exe = if ($Mode -eq "onefile") {
    "dist\pad_webdriver_ref.exe"
} else {
    "dist\pad_webdriver_ref\pad_webdriver_ref.exe"
}
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host ""
Write-Host "できあがり: $exe  ($size MB)"
Write-Host "SHA256:" (Get-FileHash $exe -Algorithm SHA256).Hash
Write-Host ""
Write-Host "動作確認:"
Write-Host "  $exe --batch examples\pad\pad_sample_batch.json ``"
Write-Host "      --details `"C:\temp\sample_batch.csv`" --id-column ID ``"
Write-Host "      --robin output\pad_sample.robin.txt ``"
Write-Host "      --driver-exe `"C:\temp\msedgedriver.exe`" --pad-out-dir `"C:\temp`" ``"
Write-Host "      --pad-browser edge --auto-driver"
