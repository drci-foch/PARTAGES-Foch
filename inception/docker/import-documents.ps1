# Import des documents .txt dans les 3 projets PARTAGES via l'API AERO.
#
# Attend, a cote du dossier docker\, les dossiers de corpus :
#   ..\CU1\*.txt   -> projet dont le titre contient "CU1"
#   ..\CU5a\*.txt  -> projet dont le titre contient "CU5a"
#   ..\CU5b\*.txt  -> projet dont le titre contient "CU5b"
#
# Usage : .\import-documents.ps1 -Url http://localhost:8080 -User admin -Password 'motdepasse'
# Relancable : les documents deja presents sont ignores (l'API repond 409).
param(
    [string]$Url = "http://localhost:8080",
    [string]$User = "admin",
    [Parameter(Mandatory = $true)][string]$Password
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

$projects = (& curl.exe -s -u "${User}:${Password}" "$Url/api/aero/v1/projects" | ConvertFrom-Json).body
if (-not $projects) {
    Write-Host "ECHEC : impossible de lister les projets sur $Url (identifiants ? provision fait ?)"
    exit 1
}

foreach ($cu in "CU1", "CU5a", "CU5b") {
    $proj = $projects | Where-Object { $_.title -match "_$cu(_|$)" } | Select-Object -First 1
    if (-not $proj) { $proj = $projects | Where-Object { $_.title -match $cu } | Select-Object -First 1 }
    $dir = Join-Path $root $cu
    if (-not $proj) { Write-Host "ECHEC $cu : projet introuvable - lancez d'abord provision.ps1"; continue }
    if (-not (Test-Path $dir)) { Write-Host "ECHEC $cu : dossier de corpus absent : $dir"; continue }

    # Documents deja presents dans le projet (idempotence)
    $existingDocs = (& curl.exe -s -u "${User}:${Password}" `
        "$Url/api/aero/v1/projects/$($proj.id)/documents" | ConvertFrom-Json).body.name
    $existingSet = @{}
    foreach ($n in $existingDocs) { $existingSet[$n] = $true }

    $files = Get-ChildItem "$dir\*.txt"
    $ok = 0; $skip = 0; $err = 0
    foreach ($f in $files) {
        if ($existingSet.ContainsKey($f.Name)) { $skip++; continue }
        $http = & curl.exe -s -o NUL -w "%{http_code}" -u "${User}:${Password}" `
            -F "content=@$($f.FullName)" -F "name=$($f.Name)" -F "format=text" `
            "$Url/api/aero/v1/projects/$($proj.id)/documents"
        switch ($http) {
            { $_ -in "200", "201" } { $ok++ }
            default                 { $err++; Write-Host "   ECHEC $($f.Name) : HTTP $http" }
        }
    }
    Write-Host "-> $cu (projet $($proj.id)) : $ok importes, $skip deja presents, $err erreurs, sur $($files.Count) fichiers"
}

Write-Host "Termine. Verifiez les volumes dans l'interface (Settings -> Documents de chaque projet)."
