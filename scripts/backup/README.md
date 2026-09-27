# Production backups

Three independent copies. Losing any one of them — the EC2 disk, the Mac mini,
or the AWS account — still leaves two.

| where | what | when | kept | script |
|---|---|---|---|---|
| **EC2 box** `/var/backups/marjaan` | DB dump + server config | 03:15 Cairo nightly | 7 nights | `server-backup.sh` (timer) |
| **S3** `marjaan-odoo-backups-<acct>` | DB dump + config + filestore | same run | dumps 180 d, filestore forever | `server-backup.sh` |
| **Mac mini** `~/MarjaanBackups` | DB dump + config + filestore (+ Neon, optional) | your cron | 30 nightly + 12 monthly | `backup-to-local.sh` |

The on-box copy protects against bad data edits (fast, no network). It does
**not** protect against losing the disk — S3 and the Mac mini do.

Every dump is verified before it counts: `pg_restore -l` reads the archive back
on the server and a sha256 is re-checked after every transfer. A full restore
into a scratch database was tested on 2026-09-27 (row counts matched live).

## What's in a backup

- **Database** — `pg_dump -Fc` of `marjaan` (~80 MB compressed).
- **Filestore** — `/opt/odoo/.local/share/Odoo/filestore/marjaan` (~570 MB,
  product photos + PDFs). Odoo names attachments by content hash and never
  rewrites one, so the copy is an *additive mirror*: it never deletes, and is
  therefore valid for **every** older dump, not just the newest.
- **Server config** — `/etc/odoo.conf`, systemd drop-ins, the `ee-odoo-bin`
  wrapper, watchdog, nginx site, logrotate rules, Pulse env. None of this is
  in git; a rebuilt box needs all of it. **Contains secrets** (mode 0600).

## Mac mini setup (once)

```bash
# 1. key where cron can read it (cron cannot read ~/Documents on macOS)
cp ~/Documents/marjaan-odoo-19.pem ~/.ssh/ && chmod 600 ~/.ssh/marjaan-odoo-19.pem

# 2. dry run by hand — first run copies the whole filestore (~30 min)
~/Projects/odoo-gold-pricing-engine/scripts/backup/backup-to-local.sh

# 3. nightly at 04:30 (after the server's own run)
( crontab -l 2>/dev/null; echo '30 4 * * * $HOME/Projects/odoo-gold-pricing-engine/scripts/backup/backup-to-local.sh >> $HOME/MarjaanBackups/cron.log 2>&1' ) | crontab -
```

Optional overrides in `~/.config/marjaan-backup.env` (`MARJAAN_BACKUP_DIR`,
`KEEP_DAILY`, `KEEP_MONTHLY`, `NEON_DATABASE_URL` for the ops-app DB — needs
`brew install libpq`). Health check: `cat ~/MarjaanBackups/last-success`.

The Mac must be awake at 04:30: System Settings → Energy → *Prevent automatic
sleeping*, or schedule a wake (`sudo pmset repeat wake MTWRFSU 04:25:00`).

## Cloud (S3) setup (once)

1. AWS console → CloudShell (region us-east-1) → paste all of
   `aws-setup-cloudshell.sh` → Enter.
2. It prints 3 lines. Put them in `/etc/marjaan-backup.env` on the server
   (root, 0600) — the file already exists with empty values.
3. Next night's run uploads. To test now: `sudo systemctl start marjaan-backup`
   then `sudo journalctl -u marjaan-backup -n 20`.

The server key is **write-only** (put + list, no get, no delete) and the bucket
is versioned: a compromised server can neither read the backups nor destroy
them. Restores use *your* admin credentials.

## Installing on the server (or after an EC2 rebuild)

```bash
scp -i KEY scripts/backup/{server-backup.sh,install-server-backup.sh} ubuntu@HOST:/tmp/
ssh -i KEY ubuntu@HOST 'sudo bash /tmp/install-server-backup.sh /tmp/server-backup.sh'
```

Failures alert through Revenax Pulse (`job-failed`, "Nightly backup failed").

## Restoring

Always restore into a **new** database first and check it; never over `marjaan`.

```bash
# on the server
sudo -u postgres createdb -O odoo marjaan_restore
sudo -u postgres pg_restore -d marjaan_restore --no-owner --role=odoo /var/backups/marjaan/db/marjaan-YYYYMMDD-HHMMSS.dump
# filestore: Odoo looks for <data_dir>/filestore/<dbname>
sudo rsync -a /opt/odoo/.local/share/Odoo/filestore/marjaan/ /opt/odoo/.local/share/Odoo/filestore/marjaan_restore/
```

From the Mac copy: `scp` the `.dump` up first; filestore via
`rsync -a ~/MarjaanBackups/filestore/ ubuntu@HOST:/tmp/fs/` then `sudo mv`.
From S3: `aws s3 cp s3://BUCKET/db/<file> .` and
`aws s3 sync s3://BUCKET/filestore/ <filestore dir>` (admin credentials).

To go live on a restored DB: stop Odoo, swap names
(`ALTER DATABASE marjaan RENAME TO marjaan_broken; ALTER DATABASE marjaan_restore RENAME TO marjaan;`),
rename the filestore directory to match, start Odoo. `dbfilter = ^marjaan$`
means only the database named exactly `marjaan` is ever served.
