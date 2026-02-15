#!/usr/bin/env bash
# Manage the quarry-embedding SageMaker CloudFormation stack.
# Usage: ./infra/manage-stack.sh [deploy|destroy|status]

set -euo pipefail

STACK_NAME="quarry-embedding"
REGION="us-west-1"
PROFILE="admin"
INFRA_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$INFRA_DIR/sagemaker-embedding.yaml"
S3_BUCKET="quarry-models-975377310343"
S3_KEY="sagemaker/quarry-embedding/model.tar.gz"

upload_inference_code() {
  echo "Packaging custom inference handler..."
  local tmptar
  tmptar="$(mktemp /tmp/quarry-model-XXXXXX.tar.gz)"
  tar -czf "$tmptar" -C "$INFRA_DIR/sagemaker-inference" code/
  echo "Uploading to s3://$S3_BUCKET/$S3_KEY..."
  aws s3 cp "$tmptar" "s3://$S3_BUCKET/$S3_KEY" \
    --region "$REGION" \
    --profile "$PROFILE"
  rm -f "$tmptar"
}

case "${1:-}" in
  deploy)
    upload_inference_code
    echo "Deploying $STACK_NAME in $REGION..."
    # Delete if in ROLLBACK_COMPLETE state
    STATUS=$(aws cloudformation describe-stacks \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --profile "$PROFILE" \
      --query "Stacks[0].StackStatus" \
      --output text 2>/dev/null || echo "DOES_NOT_EXIST")
    if [ "$STATUS" = "ROLLBACK_COMPLETE" ]; then
      echo "Stack in ROLLBACK_COMPLETE — deleting first..."
      aws cloudformation delete-stack \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --profile "$PROFILE"
      aws cloudformation wait stack-delete-complete \
        --stack-name "$STACK_NAME" \
        --region "$REGION" \
        --profile "$PROFILE"
    fi
    aws cloudformation deploy \
      --template-file "$TEMPLATE" \
      --stack-name "$STACK_NAME" \
      --capabilities CAPABILITY_NAMED_IAM \
      --region "$REGION" \
      --profile "$PROFILE" \
      --parameter-overrides "ModelDataBucket=$S3_BUCKET" "ModelDataKey=$S3_KEY" \
      "${@:2}"
    echo "Done. Run 'quarry doctor' to verify."
    ;;
  destroy)
    echo "Deleting $STACK_NAME in $REGION..."
    aws cloudformation delete-stack \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --profile "$PROFILE"
    aws cloudformation wait stack-delete-complete \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --profile "$PROFILE"
    echo "Stack deleted."
    ;;
  status)
    aws cloudformation describe-stacks \
      --stack-name "$STACK_NAME" \
      --region "$REGION" \
      --profile "$PROFILE" \
      --query "Stacks[0].{Status:StackStatus,Created:CreationTime,Updated:LastUpdatedTime}" \
      --output table 2>/dev/null || echo "Stack does not exist."
    ;;
  *)
    echo "Usage: $0 {deploy|destroy|status}"
    echo ""
    echo "  deploy   Package inference code, upload to S3, deploy stack"
    echo "  destroy  Delete the stack and all resources"
    echo "  status   Show current stack status"
    echo ""
    echo "Extra args after 'deploy' are passed to cloudformation deploy."
    echo "Example: $0 deploy --parameter-overrides InstanceType=ml.m5.large"
    exit 1
    ;;
esac
