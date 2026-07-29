# Deploy BudgetBot on Oracle Cloud Free Tier

Private personal assistant · Telegram long-polling · **preserve `personal_data/`**

## Polling vs webhook

**Use long polling** (default). Do not set up webhooks on day one.

- Outbound HTTPS only — no public 443 / TLS needed  
- Fine for a private allowlisted bot  
- Latency is dominated by Ollama/Gemma, not Telegram transport  

See the deployment plan notes: single poller, systemd restart, backup data.

## Hard rule: do not wipe users

| Do | Don't |
|----|--------|
| Copy **entire** `personal_data/` (registry + users) | `make data-reset` / `rm -rf personal_data` on prod |
| Verify with `scripts/verify_personal_data.py` before start | Start bot on empty data then overwrite registry |
| Keep same bot token + allowlist | Run laptop + Oracle polling together |

---

## 1. Create the VM

1. Oracle Cloud → Compute → Instance  
2. Shape: **VM.Standard.A1.Flex** (Ampere), **1–2 OCPU, 6–12 GB RAM** if available  
3. Image: Ubuntu 22.04 or 24.04  
4. SSH key + public IP  
5. Security list: **ingress TCP 22 from your IP only**; egress allow HTTPS  

```bash
ssh ubuntu@<PUBLIC_IP>
```

---

## 2. Package on your laptop (preserves data)

```bash
cd ~/Desktop/Exp/budgetbot
make stop                    # stop local Telegram poller
bash scripts/package_for_oracle.sh
```

Produces under `~/budgetbot-oracle-package/`:

- `budgetbot-app-*.tgz` — code only  
- `budgetbot-personal-data-*.tgz` — **all users** (keep private)

Also keep a copy of `.env` offline (never commit it).

```bash
# optional local verify before shipping
PYTHONPATH=. python scripts/verify_personal_data.py --expect-identities 3
```

---

## 3. Upload to Oracle

```bash
# from laptop — adjust IP and paths
export ORACLE_IP=x.x.x.x
scp ~/budgetbot-oracle-package/budgetbot-app-*.tgz ubuntu@$ORACLE_IP:~/
scp ~/budgetbot-oracle-package/budgetbot-personal-data-*.tgz ubuntu@$ORACLE_IP:~/
scp ~/Desktop/Exp/budgetbot/.env ubuntu@$ORACLE_IP:~/budgetbot.env
```

---

## 4. Install on the VM

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip ffmpeg make

mkdir -p ~/budgetbot && cd ~/budgetbot
tar -xzf ~/budgetbot-app-*.tgz
tar -xzf ~/budgetbot-personal-data-*.tgz   # creates ./personal_data

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# optional if you want voice and have RAM:
# pip install faster-whisper

mv ~/budgetbot.env ~/budgetbot/.env
chmod 600 .env
chmod 700 personal_data personal_data/users
chmod 600 personal_data/registry.sqlite3 personal_data/users/*.sqlite3 2>/dev/null || true
```

Edit `.env` on the server:

```bash
PERSONAL_DATA_DIR=/home/ubuntu/budgetbot/personal_data
# same TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_IDS as laptop
# if RAM is low:
# ENABLE_VOICE_PROCESSING=False
# STT_PROVIDER=none
```

**Gate — must pass before starting the bot:**

```bash
cd ~/budgetbot && source .venv/bin/activate
PYTHONPATH=. python scripts/verify_personal_data.py --min-users 1
# optional: --expect-identities 3  if you know exact count
```

---

## 5. systemd service

```bash
sudo cp deploy/oracle/budgetbot-telegram.service /etc/systemd/system/
# Edit User/paths if not ubuntu@/home/ubuntu/budgetbot
sudo nano /etc/systemd/system/budgetbot-telegram.service

sudo systemctl daemon-reload
sudo systemctl enable --now budgetbot-telegram
sudo systemctl status budgetbot-telegram
journalctl -u budgetbot-telegram -f
```

Confirm laptop is **not** still running `make telegram`.

---

## 6. Smoke test (existing users)

1. Message the bot from an **existing** allowlisted account  
2. Ask something that uses history (e.g. recent spend / a remembered preference)  
3. Confirm you are **not** treated as a brand-new empty user  
4. Log a small expense; verify the same user file under `personal_data/users/` updates  

If someone gets a fresh empty onboarding, **stop the service** and restore `personal_data` from the data tarball.

---

## 7. Daily backup on the VM

```bash
mkdir -p ~/backups
crontab -e
```

```cron
0 3 * * * tar -czf /home/ubuntu/backups/personal_data-$(date +\%F).tgz -C /home/ubuntu/budgetbot personal_data && find /home/ubuntu/backups -name 'personal_data-*.tgz' -mtime +14 -delete
```

Copy backups off the VM periodically (`scp` or Object Storage).

---

## Updates (safe — does not wipe data)

```bash
cd ~/budgetbot
# if using git clone instead of tarball:
# git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart budgetbot-telegram
```

---

## Troubleshooting

| Symptom | Action |
|---------|--------|
| `Conflict: getUpdates` | Only one poller — stop laptop / other VMs |
| Bot won't start: allowlist | Set `TELEGRAM_ALLOWED_USER_IDS` |
| Users look brand new | Registry missing/wrong — restore full `personal_data` |
| OOM / killed | More RAM or disable voice STT |
| Service inactive after reboot | `systemctl enable budgetbot-telegram` |

---

## Quick reference

```bash
# laptop
make stop
make oracle-package
make verify-data

# VM
systemctl status budgetbot-telegram
journalctl -u budgetbot-telegram -f
PYTHONPATH=. python scripts/verify_personal_data.py
```
