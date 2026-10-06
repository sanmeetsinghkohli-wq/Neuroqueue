# Windows task runner:  ./dev.ps1 dev | api | web | test | train | sim | seed
param([Parameter(Position = 0)][string]$Target = "dev")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
switch ($Target) {
  "api"   { Set-Location "$root\backend"; & $py -m uvicorn app.main:app --reload --port 8000 }
  "web"   { Set-Location "$root\frontend"; npm run dev }
  "dev"   {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; & '$py' -m uvicorn app.main:app --reload --port 8000"
    Set-Location "$root\frontend"; npm run dev
  }
  "test"  { Set-Location "$root\backend"; & $py -m pytest tests -q }
  "train" { Set-Location $root; & $py -m ml.train }
  "sim"   { Set-Location $root; & $py sim/queue_simulation.py }
  "seed"  { Set-Location "$root\backend"; & $py seed.py }
  default { Write-Host "Unknown target '$Target'. Use: dev, api, web, test, train, sim, seed" }
}
