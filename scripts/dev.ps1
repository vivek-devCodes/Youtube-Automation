# Start backend (inline workers, SQLite) and frontend for local development on Windows.
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$root\backend\.venv")) {
  python -m venv "$root\backend\.venv"
  & "$root\backend\.venv\Scripts\pip" install -r "$root\backend\requirements.txt"
}
if (-not (Test-Path "$root\frontend\node_modules")) { Push-Location "$root\frontend"; npm install; Pop-Location }
Start-Process -FilePath "$root\backend\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","app.main:app","--port","8000" -WorkingDirectory "$root\backend"
Push-Location "$root\frontend"; npm run dev; Pop-Location
