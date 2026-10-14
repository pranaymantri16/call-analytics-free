param([Parameter(Mandatory = $true)][string]$DeviceId)
$ErrorActionPreference = 'Stop'
if ($DeviceId -notmatch '^[A-Za-z0-9_-]{1,128}$') { throw 'Use the device ID shown in the APK dashboard.' }
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$envPath = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) { throw 'Project .env is missing.' }
$lines = [IO.File]::ReadAllLines($envPath)
$deviceLine = $lines | Where-Object { $_ -match '^MOBILE_DEVICES=' } | Select-Object -Last 1
$devices = @{}
if ($deviceLine) {
    $json = $deviceLine.Substring('MOBILE_DEVICES='.Length).Trim().Trim("'")
    $object = $json | ConvertFrom-Json
    foreach ($property in $object.PSObject.Properties) { $devices[$property.Name] = $property.Value }
}
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
$devices[$DeviceId] = $token
$json = ConvertTo-Json -InputObject $devices -Compress
$updated = @($lines | Where-Object { $_ -notmatch '^MOBILE_(ENABLED|DEVICES)=' }) + 'MOBILE_ENABLED=true' + "MOBILE_DEVICES='$json'"
$temporary = "$envPath.mobile.tmp"
[IO.File]::WriteAllLines($temporary, $updated, (New-Object Text.UTF8Encoding($false)))
Move-Item -LiteralPath $temporary -Destination $envPath -Force
Write-Host 'Device provisioned. Enter this token in the APK Settings, then keep it private:'
Write-Host $token
Write-Host 'Reload configuration with: docker compose up -d --force-recreate backend worker beat'
