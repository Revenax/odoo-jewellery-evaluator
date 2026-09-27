#!/usr/bin/env bash
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
#
# ONE-TIME: create the backup bucket and a write-only key. Run it in AWS
# CloudShell (console, top bar ">_" icon, region us-east-1) as an admin:
#   paste this whole file, press Enter. Re-running is safe.
#
# What you get:
#   bucket  marjaan-odoo-backups-<account>   private, encrypted, versioned, TLS-only
#   user    marjaan-backup-writer            s3:PutObject + s3:ListBucket ONLY
#
# Why write-only: the key lives on the server. If the server is ever
# compromised, the attacker can write junk but can NOT read a single customer
# record out of the backups, and can NOT delete them (versioning keeps every
# prior object version; the key has no DeleteObject). Restores are done with
# YOUR admin credentials, never with this key.
#
# Cost at current size (~75 MB dump/night, ~0.6 GB filestore): well under
# US$1/month.

set -euo pipefail
REGION=us-east-1
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="marjaan-odoo-backups-$ACCOUNT"
USER=marjaan-backup-writer

aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null || aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'
aws s3api put-bucket-policy --bucket "$BUCKET" --policy "{
  \"Version\":\"2012-10-17\",
  \"Statement\":[{\"Sid\":\"TLSOnly\",\"Effect\":\"Deny\",\"Principal\":\"*\",\"Action\":\"s3:*\",
    \"Resource\":[\"arn:aws:s3:::$BUCKET\",\"arn:aws:s3:::$BUCKET/*\"],
    \"Condition\":{\"Bool\":{\"aws:SecureTransport\":\"false\"}}}]}"
# Nightly dumps: 180 days. Filestore + config: kept. Superseded versions: 60 days.
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration '{
  "Rules":[
    {"ID":"db-dumps-180d","Status":"Enabled","Filter":{"Prefix":"db/"},
     "Expiration":{"Days":180},"NoncurrentVersionExpiration":{"NoncurrentDays":60}},
    {"ID":"old-versions-60d","Status":"Enabled","Filter":{"Prefix":""},
     "NoncurrentVersionExpiration":{"NoncurrentDays":60},
     "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}]}'

aws iam get-user --user-name "$USER" >/dev/null 2>&1 || aws iam create-user --user-name "$USER" >/dev/null
aws iam put-user-policy --user-name "$USER" --policy-name write-only-backups --policy-document "{
  \"Version\":\"2012-10-17\",
  \"Statement\":[
    {\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\",\"s3:AbortMultipartUpload\"],\"Resource\":\"arn:aws:s3:::$BUCKET/*\"},
    {\"Effect\":\"Allow\",\"Action\":\"s3:ListBucket\",\"Resource\":\"arn:aws:s3:::$BUCKET\"}]}"

# Rotate: drop any older keys so only the one printed below is live.
for k in $(aws iam list-access-keys --user-name "$USER" --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
  aws iam delete-access-key --user-name "$USER" --access-key-id "$k"
done
read -r KID SECRET < <(aws iam create-access-key --user-name "$USER" \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)

cat <<OUT

================ DONE — put these 3 lines in /etc/marjaan-backup.env ================
BACKUP_BUCKET=$BUCKET
AWS_ACCESS_KEY_ID=$KID
AWS_SECRET_ACCESS_KEY=$SECRET
====================================================================================
(Write-only key: it cannot read or delete backups. Treat it as a secret anyway.)
OUT
