# Assemble le dossier de deploiement INCEpTION a copier sur le reseau interne Foch.
#
# Contenu du paquet :
#   README.md (guide de mise en prod), docker/ (kit), templates PARTAGES,
#   CU1/ CU5a/ CU5b/ (les .txt a annoter, depuis les output/ des pipelines).
#
# Usage : .\make_livraison.ps1 [-Dest <chemin>]
param(
    [string]$Dest = "C:\Users\benysar\Documents\INCEPTION-DEPLOIEMENT-FOCH"
)

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$inception = Join-Path $repo "inception"

$corpus = @{
    "CU1"  = Join-Path $repo "WP1_CU1\output\txt"
    "CU5a" = Join-Path $repo "WP5_CU5a\output\txt"
    "CU5b" = Join-Path $repo "WP5_CU5b\output\txt"
}

# Verification des sources avant de construire quoi que ce soit
$missing = $corpus.GetEnumerator() | Where-Object { -not (Test-Path $_.Value) }
if ($missing) {
    $missing | ForEach-Object { Write-Host "ECHEC : corpus absent : $($_.Value)" }
    Write-Host "Lancez les pipelines d'extraction correspondants avant de construire le paquet."
    exit 1
}

if (Test-Path $Dest) {
    Write-Host "Le dossier $Dest existe deja - il sera remplace."
    Remove-Item -Recurse -Force $Dest -Confirm:$false
}
New-Item -ItemType Directory -Path $Dest | Out-Null

# 1. Guide de mise en prod -> README.md a la racine du paquet
Copy-Item (Join-Path $inception "docker\README-MISE-EN-PROD.md") (Join-Path $Dest "README.md")

# 2. Kit docker (sans les donnees locales ./data ni le guide deja copie)
$dockerDest = Join-Path $Dest "docker"
New-Item -ItemType Directory -Path $dockerDest | Out-Null
foreach ($f in "docker-compose.yml", "settings.properties", "provision.sh", "provision.ps1",
              "import-documents.sh", "import-documents.ps1", "README.md") {
    Copy-Item (Join-Path $inception "docker\$f") $dockerDest
}

# 3. Templates PARTAGES (attendus par provision.* a la racine du paquet)
Copy-Item (Join-Path $inception "Template INCEpTION - Tags et Label CU1, CU5a, CU5b.zip") $Dest

# 4. Corpus .txt
foreach ($cu in $corpus.Keys) {
    $cuDest = Join-Path $Dest $cu
    New-Item -ItemType Directory -Path $cuDest | Out-Null
    Copy-Item (Join-Path $corpus[$cu] "*.txt") $cuDest
    $n = (Get-ChildItem "$cuDest\*.txt").Count
    Write-Host ("  {0,-5} : {1} fichiers .txt" -f $cu, $n)
}

Write-Host ""
Write-Host "Paquet construit : $Dest"
Write-Host "RAPPEL avant remise a l'admin prod :"
Write-Host "  - le hash admin dans docker\settings.properties est celui du test local ;"
Write-Host "    l'admin prod DOIT le remplacer (etape 2 du README du paquet)."
Write-Host "  - copier le dossier UNIQUEMENT sur le reseau interne Foch (donnees patient)."
