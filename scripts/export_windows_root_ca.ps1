param(
    [Parameter(Mandatory = $false)]
    [string]$CommonName = "Norton Web/Mail Shield Root",

    [Parameter(Mandatory = $false)]
    [string]$OutputPath = ".local-certs/local-root-ca.crt"
)

$ErrorActionPreference = "Stop"

$certificate = Get-ChildItem Cert:\CurrentUser\Root, Cert:\LocalMachine\Root |
    Where-Object { $_.Subject -like "*CN=$CommonName*" } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if ($null -eq $certificate) {
    throw "No trusted Windows root certificate with CN '$CommonName' was found."
}

if ($certificate.HasPrivateKey) {
    throw "Refusing to export a certificate that exposes a private key."
}

$resolvedOutput = Join-Path (Get-Location) $OutputPath
$directory = Split-Path -Parent $resolvedOutput
New-Item -ItemType Directory -Force -Path $directory | Out-Null

$base64 = [Convert]::ToBase64String(
    $certificate.RawData,
    [Base64FormattingOptions]::InsertLineBreaks
)
$pem = "-----BEGIN CERTIFICATE-----`r`n$base64`r`n-----END CERTIFICATE-----`r`n"
[IO.File]::WriteAllText($resolvedOutput, $pem, [Text.Encoding]::ASCII)

Write-Host "Exported public root CA $($certificate.Thumbprint) to $resolvedOutput"
