param(
  [Parameter(Mandatory=$true)][string]$ServerUrl,
  [Parameter(Mandatory=$true)][string]$ApiToken,
  [Parameter(Mandatory=$true)][string]$FilePath,
  [string]$DocumentDate = ""
)

if (!(Test-Path -LiteralPath $FilePath)) { throw "File does not exist: $FilePath" }
if ([IO.Path]::GetExtension($FilePath).ToLowerInvariant() -ne ".docx") { throw "Only .docx files are accepted" }

$base = $ServerUrl.TrimEnd("/")
$headers = @{ Authorization = "Bearer $ApiToken" }
$form = @{ file = Get-Item -LiteralPath $FilePath }
if ($DocumentDate) { $form.document_date = $DocumentDate }
$response = Invoke-RestMethod -Method Post -Uri "$base/api/documents/upload" -Headers $headers -Form $form
Write-Host "job_id=$($response.job_id)"

while ($true) {
  Start-Sleep -Seconds 2
  $job = Invoke-RestMethod -Method Get -Uri "$base/api/jobs/$($response.job_id)" -Headers $headers
  Write-Host "$($job.status) $($job.progress)% $($job.current_step)"
  if ($job.status -eq "done") {
    Write-Host "Exports: $base/exports"
    break
  }
  if ($job.status -eq "failed") {
    throw "Job failed: $($job.error)"
  }
}
