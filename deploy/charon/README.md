# PEARL Charon handoff

Charon is the sole post-sentinel control plane for the frozen Frontier Adaptation v2 replication
cohort. It runs inside Ubuntu 24.04 under WSL2. Tinker remains the remote training provider; the
Windows host needs no GPU.

## Host requirements

- x86-64 Windows 10 or 11 with virtualization and WSL2 support;
- at least 16 GiB RAM and 50 GiB free SSD space;
- stable outbound network access and continuous AC power;
- Windows sleep, hibernation, and automatic campaign-window restarts disabled;
- no competing PEARL controller on the Mac or GitHub.

The display may turn off and the Windows session may lock. The host itself must not sleep, restart,
or lose network access while Charon owns paid work.

## Installation from the USB package

1. In an Administrator PowerShell window, run `provision-windows.ps1`. Reboot if Windows requests
   it, then launch Ubuntu once and create the Linux user.
2. In Ubuntu, identify the USB path (for example `/mnt/e/PEARL_CHARON`) and run:

   ```bash
   bash /mnt/e/PEARL_CHARON/install-wsl.sh /mnt/e/PEARL_CHARON
   ```

3. Put only `TINKER_API_KEY=...` in `~/.config/pearl/charon.env`, then run `chmod 600` on it.
   Authenticate GitHub with `gh auth login` and confirm `gh auth status`.
4. Run `~/pearl-charon/bin/verify-charon.sh`. It is read-only and must pass completely.
5. The primary operator runs `~/pearl-charon/bin/arm-charon.sh` exactly once. Do not run it until
   GitHub has terminal-trained and terminal-evaluated the sentinel and the frontier supervisor is
   disabled.

`arm-charon.sh` prepares one immutable authorization, installs the systemd service, and starts it.
The service opens 12 cells, waits for the frozen result-blind health gate, opens 24, waits again,
opens all 47 remaining cells, completes training and evaluation, writes a 48/48 gate, and stops.
It contains no analysis or structural-generation entrypoint.

## Status and failure behavior

Run `~/pearl-charon/bin/status-charon.sh` at any time. It reads local operational state only.

Do not kill a trainer, restart Windows, relaunch a missing run key, enable the GitHub frontier
supervisor, or arm a second controller. An expected ownership, lineage, provider, or artifact
failure exits successfully into a durable `charon_replication_blocked` state so systemd will not
retry it. Systemd bounds rapid unexpected-crash restarts; durable launch intents prevent ambiguous
work from being resubmitted under any restart.

No secret is stored on the USB package. The package is bound by `SHA256SUMS`, and the source bundle,
frozen dataset archive, bootstrap evidence, and controller commit are cross-checked before any paid
request.
