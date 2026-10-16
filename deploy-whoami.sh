#!/usr/bin/env bash
# Deploys whoami-demo.yaml next to the authentik stack, reusing its cluster, VPC, ALB and HTTPS listener.
# Usage: ./deploy-whoami.sh   (values from .env; any variable can be overridden on the command line)
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck disable=SC1091
if [ -f .env ]; then set -a; . ./.env; set +a; fi

REGION="${REGION:-us-east-1}"
AK_STACK="${AK_STACK:-demo-authentik}"
APP_STACK="${APP_STACK:-demo-authentik-whoami}"
for v in APP_HOST AUTHENTIK_HOST CLIENT_ID CLIENT_SECRET; do
  val="${!v:-}"
  if [ -z "$val" ] || [ "$val" = "REEMPLAZAR" ] || [[ "$val" == *example.com ]]; then
    echo "Set $v in .env first" >&2; exit 1
  fi
done

# Physical IDs of the resources created by authentik-demo.yaml (logical IDs come from the CDK-generated template)
res() {
  aws cloudformation describe-stack-resource --region "$REGION" \
    --stack-name "$AK_STACK" --logical-resource-id "$1" \
    --query StackResourceDetail.PhysicalResourceId --output text
}

CLUSTER=$(res AuthentikCluster54E596EF)
VPC=$(res AuthentikVpcA1ABE6C2)
SUBNET1=$(res AuthentikVpcPublicSubnet1Subnet0C75862A)
SUBNET2=$(res AuthentikVpcPublicSubnet2Subnet4DFAFA5B)
ALB_SG=$(res AuthentikALBSecurityGroup2B18FEEF)
LISTENER=$(res AuthentikALBAuthentikHttpsListener34A9BF12)
ALB_ARN=$(aws elbv2 describe-listeners --region "$REGION" --listener-arns "$LISTENER" \
  --query "Listeners[0].LoadBalancerArn" --output text)

echo "cluster=$CLUSTER vpc=$VPC subnets=$SUBNET1,$SUBNET2 albsg=$ALB_SG"
echo "listener=$LISTENER"
echo "alb=$ALB_ARN"

# A failed first create leaves the stack in ROLLBACK_COMPLETE, which cannot be updated
STATUS=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$APP_STACK" \
  --query "Stacks[0].StackStatus" --output text 2>/dev/null || echo NONE)
if [ "$STATUS" = "ROLLBACK_COMPLETE" ]; then
  echo "Deleting $APP_STACK (ROLLBACK_COMPLETE) before redeploying..."
  aws cloudformation delete-stack --region "$REGION" --stack-name "$APP_STACK"
  aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$APP_STACK"
fi

aws cloudformation deploy --region "$REGION" \
  --stack-name "$APP_STACK" \
  --template-file whoami-demo.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ClusterName="$CLUSTER" \
    VpcId="$VPC" \
    PublicSubnets="$SUBNET1,$SUBNET2" \
    AlbSecurityGroupId="$ALB_SG" \
    HttpsListenerArn="$LISTENER" \
    OidcClientId="$CLIENT_ID" \
    OidcClientSecret="$CLIENT_SECRET" \
    AppImage="${IMAGE:-python:3.13-slim}" \
    ExpectedSignerArn="$ALB_ARN" \
    AppHostName="$APP_HOST" \
    AuthentikHost="$AUTHENTIK_HOST" \
    AuthentikAppSlug="${AUTHENTIK_APP_SLUG:-whoami}"

aws cloudformation describe-stacks --region "$REGION" --stack-name "$APP_STACK" \
  --query "Stacks[0].Outputs" --output table
