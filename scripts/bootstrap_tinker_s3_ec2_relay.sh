#!/bin/bash
set -euo pipefail

exec > >(tee -a /var/log/pearl-relay-bootstrap.log) 2>&1

ROOT=/opt/pearl-relay
BUCKET=pearl-full-checkpoint-archive-20260822
STAGE_PREFIX=control/ec2-relay-20260825/stage

# The OS shutdown is the independent compute-spend ceiling. A stopped instance
# retains its small encrypted EBS volume and can resume from verified S3 state.
shutdown -h +720

dnf install -y python3.11 python3.11-pip
mkdir -p "$ROOT"
python3.11 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install --disable-pip-version-check \
  boto3==1.43.77 botocore==1.43.77 tinker==0.25.0

aws s3 sync "s3://$BUCKET/$STAGE_PREFIX/" "$ROOT/" \
  --region us-west-1 --only-show-errors

"$ROOT/venv/bin/python" - <<'PY'
import hashlib
import json
from pathlib import Path

root = Path("/opt/pearl-relay")
manifest = json.loads((root / "stage-manifest.json").read_text(encoding="utf-8"))
if manifest.get("contract") != "pearl.tinker-s3-ec2-relay-stage/1":
    raise SystemExit("invalid relay stage manifest contract")
for row in manifest["files"]:
    path = root / row["path"]
    body = path.read_bytes()
    if len(body) != row["bytes"] or hashlib.sha256(body).hexdigest() != row["sha256"]:
        raise SystemExit(f"relay stage verification failed: {row['path']}")
print(f"verified {len(manifest['files'])} staged relay files")
PY

chmod 700 "$ROOT/scripts/export_tinker_sampler_archives_to_s3.py"
chmod 700 "$ROOT/scripts/run_tinker_s3_ec2_relay.py"

install -m 600 /dev/stdin /etc/systemd/system/pearl-tinker-s3-relay.service <<'UNIT'
[Unit]
Description=PEARL resumable Tinker to S3 relay
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/pearl-relay
ExecStart=/opt/pearl-relay/venv/bin/python /opt/pearl-relay/scripts/run_tinker_s3_ec2_relay.py --deadline-hours 12 --sync-seconds 300
Restart=on-failure
RestartSec=60
StartLimitIntervalSec=0
StandardOutput=append:/var/log/pearl-tinker-s3-relay.log
StandardError=append:/var/log/pearl-tinker-s3-relay.log

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now pearl-tinker-s3-relay.service
