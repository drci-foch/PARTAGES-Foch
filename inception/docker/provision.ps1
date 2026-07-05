# Provisionnement INCEpTION - importe les 3 projets PARTAGES (CU1, CU5a, CU5b)
# via l'API distante AERO. A lancer une fois INCEpTION demarre.
#
# Usage : .\provision.ps1 -Url http://localhost:8080 -User admin -Password 'motdepasse'
param(
    [string]$Url = "http://localhost:8080",
    [string]$User = "admin",
    [Parameter(Mandatory = $true)][string]$Password
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$masterZip = Join-Path (Split-Path -Parent $here) "Template INCEpTION - Tags et Label CU1, CU5a, CU5b.zip"
$tmp = Join-Path $env:TEMP ("inception-provision-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null

try {
    # INCEpTION renvoie HTTP 200 + page "starting up" pendant son demarrage :
    # on attend que l'API AERO reponde du JSON avant d'importer.
    Write-Host "-> Attente du demarrage complet d'INCEpTION..."
    $ready = $false
    foreach ($i in 1..60) {
        $body = & curl.exe -s -u "${User}:${Password}" "$Url/api/aero/v1/projects"
        if ($body -and $body.TrimStart().StartsWith("{")) { Write-Host "   OK API prete"; $ready = $true; break }
        Start-Sleep -Seconds 5
    }
    if (-not $ready) { Write-Host "   ECHEC API indisponible apres 5 min"; exit 1 }

    Write-Host "-> Extraction des templates depuis : $masterZip"
    Expand-Archive -Path $masterZip -DestinationPath $tmp -Force

    # Projets deja presents (idempotence : ne pas reimporter -> pas de doublon)
    $existing = (& curl.exe -s -u "${User}:${Password}" "$Url/api/aero/v1/projects" | ConvertFrom-Json).body
    $titles = @{ CU1 = "EX_PARTAGES_CU1"; CU5a = "EX_PARTAGES_CU5a"; CU5b = "EX_PARTAGES_CU5b" }

    foreach ($cu in "CU1", "CU5a", "CU5b") {
        if ($existing | Where-Object { $_.title -like "$($titles[$cu])*" }) {
            Write-Host "-> $cu deja present - ignore (relance sans doublon)"
            continue
        }
        Write-Host "-> Import du projet $cu ..."
        $zipPath = Join-Path $tmp "$cu.zip"
        # curl.exe (natif Windows 10+) gere le multipart simplement
        $resp = & curl.exe -s -o "$tmp\resp_$cu.json" -w "%{http_code}" `
            -u "${User}:${Password}" `
            -F "file=@$zipPath" `
            "$Url/api/aero/v1/projects/import"
        if ($resp -eq "200" -or $resp -eq "201") {
            Write-Host "   OK : $cu importe"
        } else {
            Write-Host "   ECHEC $cu : HTTP $resp - $(Get-Content "$tmp\resp_$cu.json" -Raw)"
            Write-Host "     (deja importe ? droits ROLE_REMOTE manquants ? remote-api.enabled=false ?)"
        }
    }

    Write-Host "-> Projets presents sur $Url :"
    & curl.exe -s -u "${User}:${Password}" "$Url/api/aero/v1/projects"
    Write-Host ""
    Write-Host "Termine. Pensez a desactiver remote-api.enabled si l'API n'est plus utile."
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
