param(
  [Parameter(Mandatory=$true)][string]$ServerUrl,
  [Parameter(Mandatory=$true)][string]$ApiToken,
  [Parameter(Mandatory=$true)][string]$OutPath
)

$base = $ServerUrl.TrimEnd("/")
$headers = @{ Authorization = "Bearer $ApiToken" }
Invoke-WebRequest -Uri "$base/api/exports/latest" -Headers $headers -OutFile $OutPath
Write-Host "Saved $OutPath"

