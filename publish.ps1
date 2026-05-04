# Vorher: Version in pyproject.toml manuell erhöhen!

Write-Host "--- Starte Build-Prozess für habitron-client ---" -ForegroundColor Cyan

# 1. Alte Build-Dateien säubern
if (Test-Path dist) { 
    Write-Host "Lösche alten dist-Ordner..."
    Remove-Item -Recurse -Force dist 
}

# 2. Paket bauen
Write-Host "Baue Paket..." -ForegroundColor Yellow
python -m build

# 3. Hochladen
Write-Host "Lade zu PyPI hoch..." -ForegroundColor Yellow
# Falls du .pypirc nutzt, geht das ohne Passwortabfrage
python -m twine upload dist/*

Write-Host "--- Fertig! ---" -ForegroundColor Green
Write-Host "Vergiss nicht: 'pip install habitron-client --upgrade' im HA-Container." -ForegroundColor Magenta