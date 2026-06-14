# /token

Check token usage for the current session. Works without junior_mark.

Run the PowerShell below and output the result:

```powershell
$projectsDir = "$env:USERPROFILE\.claude\projects"
$jsonlFile = Get-ChildItem -Path $projectsDir -Filter "*.jsonl" -Recurse |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $jsonlFile) { Write-Host "no transcript file found"; exit }

$lastUsage = $null
foreach ($line in Get-Content $jsonlFile.FullName -Encoding UTF8) {
    try {
        $obj = $line | ConvertFrom-Json
        if ($obj.message.usage) { $lastUsage = $obj.message.usage }
    } catch {}
}

if (-not $lastUsage) { Write-Host "no response yet — check again after one exchange"; exit }

$tokens = [int]$lastUsage.input_tokens + [int]$lastUsage.cache_read_input_tokens + [int]$lastUsage.cache_creation_input_tokens
$pct = [math]::Round($tokens / 167000 * 100, 1)
Write-Host "token : $("{0:N0}" -f $tokens) / 167,000 ($pct%)"
Write-Host "file  : $($jsonlFile.Name)"
```
