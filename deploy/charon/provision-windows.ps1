$ErrorActionPreference = "Stop"

Write-Host "Configuring Windows for PEARL Charon (WSL2 Ubuntu 24.04)."
wsl.exe --install --distribution Ubuntu-24.04 --no-launch

# The display may turn off. The host must not sleep or hibernate on AC power.
powercfg.exe /change standby-timeout-ac 0
powercfg.exe /change hibernate-timeout-ac 0

Write-Host "WSL2 provisioning requested. Reboot if Windows asks, then launch Ubuntu-24.04 once."
Write-Host "Pause Windows Update restarts for the campaign window before arming Charon."
