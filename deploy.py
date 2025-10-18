#!/usr/bin/env python3
"""
Fully automated deployment script for the Hackathon Hunter project.
This script is idempotent and handles the entire deployment process:
1. Deploys/Updates the CloudFormation infrastructure.
2. Builds and pushes the Scout agent's Docker image to ECR.
3. Packages and deploys the code for both Lambda functions.
4. Sets up and syncs the Bedrock Knowledge Base.
"""
import boto3
import subprocess
import os
import time
import zipfile
import logging
from botocore.exceptions import ClientError

# --- CONFIGURATION ---
STACK_NAME = "Hackathon-Hunter-Stack"
REGION = os.environ.get("AWS_REGION", "ap-south-1")
CFN_TEMPLATE_PATH = "cloudformation.yaml"
SCOUT_AGENT_DOCKER_CONTEXT = "." # Current directory contains Scout agent
NUDGE_AGENT_CODE_PATH = "." # Nudge agent in root directory
HANDLER_LAMBDA_CODE_PATH = "." # Telegram handler in root directory
TRUSTED_SOURCES_FILE = "trusted_sources.txt"

# --- SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
cf_client = boto3.client('cloudformation', region_name=REGION)
s3_client = boto3.client('s3', region_name=REGION)
ecr_client = boto3.client('ecr', region_name=REGION)
lambda_client = boto3.client('lambda', region_name=REGION)
bedrock_agent_client = boto3.client('bedrock-agent', region_name=REGION)

def get_stack_outputs():
    """Fetches and parses the outputs of the deployed CloudFormation stack."""
    try:
        response = cf_client.describe_stacks(StackName=STACK_NAME)
        outputs = response['Stacks'][0]['Outputs']
        return {o['OutputKey']: o['OutputValue'] for o in outputs}
    except ClientError as e:
        if "does not exist" in e.response['Error']['Message']:
            logging.error(f"Stack '{STACK_NAME}' does not exist. Please deploy the infrastructure first.")
            return None
        raise e

def zip_directory(path, zip_handle):
    """Creates a zip archive from a directory."""
    for root, _, files in os.walk(path):
        for file in files:
            zip_handle.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), path))

def deploy_infrastructure():
    """Deploys or updates the CloudFormation stack."""
    logging.info("Reading CloudFormation template...")
    with open(CFN_TEMPLATE_PATH, 'r') as f:
        template_body = f.read()

    try:
        cf_client.describe_stacks(StackName=STACK_NAME)
        logging.info(f"Stack '{STACK_NAME}' already exists. Initiating update...")
        waiter = cf_client.get_waiter('stack_update_complete')
        cf_client.update_stack(
            StackName=STACK_NAME,
            TemplateBody=template_body,
            Capabilities=['CAPABILITY_NAMED_IAM']
        )
        logging.info("Waiting for stack update to complete...")
        waiter.wait(StackName=STACK_NAME)
        logging.info("✅ Infrastructure updated successfully.")
    except ClientError as e:
        if "does not exist" in e.response['Error']['Message']:
            logging.info(f"Stack '{STACK_NAME}' does not exist. Creating new stack...")
            waiter = cf_client.get_waiter('stack_create_complete')
            cf_client.create_stack(
                StackName=STACK_NAME,
                TemplateBody=template_body,
                Capabilities=['CAPABILITY_NAMED_IAM']
            )
            logging.info("Waiting for stack creation to complete...")
            waiter.wait(StackName=STACK_NAME)
            logging.info("✅ Infrastructure deployed successfully.")
        else:
            raise e

def build_and_push_docker_image(ecr_uri):
    """Builds and pushes the Scout agent Docker image to ECR."""
    if not ecr_uri:
        logging.error("ECR Repository URI not found in stack outputs. Cannot build image.")
        return

    logging.info("🐳 Authenticating Docker with ECR...")
    try:
        auth_response = ecr_client.get_authorization_token()
        auth_data = auth_response['authorizationData'][0]
        token = auth_data['authorizationToken']
        endpoint = auth_data['proxyEndpoint']

        # The get_authorization_token returns a base64 encoded token in 'user:password' format.
        # Docker login expects the password separately.
        password = boto3.utils.decode_from_base64(token).decode('utf-8').split(':')[1]
        
        subprocess.run(
            ["docker", "login", "--username", "AWS", "--password-stdin", endpoint],
            input=password.encode('utf-8'), check=True
        )
        logging.info("Docker authentication successful.")
    except (ClientError, subprocess.CalledProcessError) as e:
        logging.error(f"Docker ECR authentication failed: {e}")
        return

    logging.info(f"Building Docker image from context: {SCOUT_AGENT_DOCKER_CONTEXT}")
    image_tag = f"{ecr_uri}:latest"
    try:
        subprocess.run(["docker", "build", "-t", image_tag, SCOUT_AGENT_DOCKER_CONTEXT], check=True)
        logging.info(f"Pushing image to {image_tag}...")
        subprocess.run(["docker", "push", image_tag], check=True)
        logging.info("✅ Docker image pushed to ECR successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Docker build or push failed: {e}")

def deploy_lambda_functions(stack_outputs):
    """Packages and deploys the code for both Lambda functions."""
    logging.info("📦 Packaging and deploying Lambda functions...")
    
    nudge_function_name = stack_outputs.get('NudgeLambdaFunctionName')
    handler_function_name = stack_outputs.get('TelegramHandlerFunctionName')

    if not nudge_function_name or not handler_function_name:
        logging.error("Lambda function names not found in stack outputs.")
        return

    for func_name, code_path in [
        (nudge_function_name, NUDGE_AGENT_CODE_PATH),
        (handler_function_name, HANDLER_LAMBDA_CODE_PATH)
    ]:
        logging.info(f"Deploying code for {func_name} from {code_path}...")
        zip_file_name = f"/tmp/{func_name}.zip"
        with zipfile.ZipFile(zip_file_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zip_directory(code_path, zipf)
        
        with open(zip_file_name, 'rb') as f:
            zipped_code = f.read()

        try:
            lambda_client.update_function_code(
                FunctionName=func_name,
                ZipFile=zipped_code
            )
            logging.info(f"✅ Successfully updated code for {func_name}.")
        except ClientError as e:
            logging.error(f"Failed to update code for {func_name}: {e}")
        os.remove(zip_file_name)

def setup_knowledge_base(bucket_name, kb_id):
    """Uploads trusted sources and starts the Knowledge Base sync."""
    if not bucket_name or not kb_id:
        logging.error("S3 bucket name or Knowledge Base ID not found.")
        return

    logging.info("📚 Setting up Bedrock Knowledge Base...")
    try:
        logging.info(f"Uploading {TRUSTED_SOURCES_FILE} to S3 bucket: {bucket_name}")
        s3_client.upload_file(TRUSTED_SOURCES_FILE, bucket_name, TRUSTED_SOURCES_FILE)
        logging.info("Trusted sources file uploaded.")

        logging.info(f"Starting ingestion job for Knowledge Base: {kb_id}")
        data_sources = bedrock_agent_client.list_data_sources(knowledgeBaseId=kb_id)
        if not data_sources['dataSourceSummaries']:
            logging.warning("No data sources found for the Knowledge Base. Please ensure it was created correctly.")
            return

        data_source_id = data_sources['dataSourceSummaries'][0]['dataSourceId']
        response = bedrock_agent_client.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=data_source_id
        )
        job_id = response['ingestionJob']['ingestionJobId']
        logging.info(f"✅ Knowledge Base sync started. Ingestion Job ID: {job_id}. This may take a few minutes to complete in the AWS console.")

    except (ClientError, FileNotFoundError) as e:
        logging.error(f"Knowledge Base setup failed: {e}")

def main():
    """Main deployment orchestration flow."""
    logging.info("🚀 Starting Hackathon Hunter Deployment 🚀")
    
    # 1. Deploy Infrastructure
    deploy_infrastructure()
    
    # 2. Get Stack Outputs
    outputs = get_stack_outputs()
    if not outputs:
        logging.error("Failed to retrieve stack outputs. Halting deployment.")
        return

    # 3. Deploy Scout Agent Code
    build_and_push_docker_image(outputs.get('ECRRepositoryURI'))

    # 4. Deploy Lambda Functions Code
    deploy_lambda_functions(outputs)

    # 5. Setup and Sync Knowledge Base
    setup_knowledge_base(outputs.get('S3BucketName'), outputs.get('KnowledgeBaseId'))
    
    logging.info("\n🎉 Deployment Summary & Next Steps 🎉")
    logging.info("=" * 40)
    logging.info(f"✅ Infrastructure is DEPLOYED/UPDATED in region {REGION}.")
    logging.info(f"✅ Scout Agent Docker image is PUSHED to ECR.")
    logging.info(f"✅ Nudge & Handler Lambda function code is DEPLOYED.")
    logging.info(f"✅ Knowledge Base sync has been INITIATED.")
    logging.info("-" * 40)
    logging.info("📋 Final Manual Step:")
    logging.info(f"1. Set your Telegram Bot's webhook to the following URL:")
    logging.info(f"   -> {outputs.get('TelegramWebhookURL')}")
    logging.info("=" * 40)

if __name__ == "__main__":
    main()
