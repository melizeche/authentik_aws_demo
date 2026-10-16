#!/usr/bin/env bash
# Creates or updates the authentik stack (authentik-demo.yaml) using the values in .env.
# Usage: ./deploy-authentik.sh            (preview the change set: PREVIEW=1 ./deploy-authentik.sh)
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck disable=SC1091
if [ -f .env ]; then set -a; . ./.env; set +a; fi

REGION="${REGION:-us-east-1}"
AK_STACK="${AK_STACK:-demo-authentik}"
AK_TEMPLATE="${AK_TEMPLATE:-authentik-demo.yaml}"
: "${CERT_ARN:?set CERT_ARN in .env}"
case "$CERT_ARN" in *REEMPLAZAR*) echo "Set CERT_ARN in .env first" >&2; exit 1;; esac

EXTRA=()
if [ "${PREVIEW:-0}" = "1" ]; then EXTRA+=(--no-execute-changeset); fi

aws cloudformation deploy --region "$REGION" \
  --stack-name "$AK_STACK" \
  --template-file "$AK_TEMPLATE" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    CertificateARN="$CERT_ARN" \
    AuthentikVersion="${AUTHENTIK_VERSION:-2026.8.4}" \
    DBVersion="${DB_VERSION:-17}" \
    DBInstanceType="${DB_INSTANCE_TYPE:-t4g.small}" \
  ${EXTRA[@]+"${EXTRA[@]}"}

aws cloudformation describe-stacks --region "$REGION" --stack-name "$AK_STACK" \
  --query "Stacks[0].[StackStatus,Outputs]" --output text
