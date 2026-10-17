# Run as Administrator only if other LAN devices cannot connect.
# Restricts access to this port and the local subnet; does not disable the firewall.
$ErrorActionPreference='Stop'
$name='Dreamina Canvas Results LAN 8769'
if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8769 -RemoteAddress LocalSubnet -Profile Any | Out-Null
}
Write-Host 'LAN access allowed for TCP 8769 (LocalSubnet only).'
