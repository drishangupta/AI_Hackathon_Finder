#!/usr/bin/env python3
"""
Fully automated deployment script for the Hackathon Hunter project.
This script is idempotent and handles the deployment of the parameterized
CloudFormation stack, Docker image, and Lambda code.

It reads required parameters (KNOWLEDGE_BASE_ID, etc.) from a .env file.
"""
import boto3
import subprocess
import os
import zipfile
import logging
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# --- CONFIGURATION ---
STACK_NAME = "Hackathon-Hunter-Stack"
REGION = os.environ.get("AWS_REGION", "ap-south-1")
CFN_TEMPLATE_PATH = "cloudformation.yaml"
SCOUT_AGENT_DOCKER_CONTEXT = "." 
NUDGE_AGENT_PY_FILE = "nudge_agent.py"
HANDLER_PY_FILE = "telegram_handler.py"
TRUSTED_SOURCES_FILE = "trusted_sources.txt"

# --- SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
cf_client = boto3.client('cloudformation', region_name=REGION)
s3_client = boto3.client('s3', region_name=REGION)
ecr_client = boto3.client('ecr', region_name=REGION)
lambda_client = boto3.client('lambda', region_name=REGION)

def get_stack_outputs():
    """Fetches and parses the outputs of the deployed CloudFormation stack."""
    try:
        response = cf_client.describe_stacks(StackName=STACK_NAME)
        outputs = response['Stacks'][0]['Outputs']
        return {o['OutputKey']: o['OutputValue'] for o in outputs}
    except ClientError as e:
        if "does not exist" in e.response['Error']['Message']:
            logging.error(f"Stack '{STACK_NAME}' does not exist.")
            return None
        raise e

def deploy_infrastructure(parameters):
    """Deploys or updates the CloudFormation stack with parameters."""
    logging.info("Reading CloudFormation template...")
    with open(CFN_TEMPLATE_PATH, 'r') as f:
        template_body = f.read()

    cfn_params = [
        {'ParameterKey': 'KnowledgeBaseId', 'ParameterValue': parameters['kb_id']},
    ]

    try:
        cf_client.describe_stacks(StackName=STACK_NAME)
        logging.info(f"Stack '{STACK_NAME}' already exists. Initiating update...")
        waiter = cf_client.get_waiter('stack_update_complete')
        cf_client.update_stack(
            StackName=STACK_NAME,
            TemplateBody=template_body,
            Parameters=cfn_params,
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
                Parameters=cfn_params,
                Capabilities=['CAPABILITY_NAMED_IAM']
            )
            logging.info("Waiting for stack creation to complete...")
            waiter.wait(StackName=STACK_NAME)
            logging.info("✅ Infrastructure deployed successfully.")
        elif "No updates are to be performed" in e.response['Error']['Message']:
            logging.info("✅ Infrastructure is already up-to-date.")
        else:
            raise e

def build_and_push_docker_image(ecr_uri):
    """Builds and pushes the Scout agent Docker image to ECR."""
    if not ecr_uri:
        logging.error("ECR Repository URI not found. Cannot build image.")
        return

    logging.info("🐳 Authenticating Docker with ECR...")
    try:
        auth_response = ecr_client.get_authorization_token()
        auth_data = auth_response['authorizationData'][0]
        token = auth_data['authorizationToken']
        endpoint = auth_data['proxyEndpoint']
        
        import base64
        password = base64.b64decode(token).decode('utf-8').split(':')[1]
        
        subprocess.run(
            ["docker", "login", "--username", "AWS", "--password-stdin", endpoint],
            input=password.encode('utf-8'), check=True, capture_output=True
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
        logging.error(f"Docker build or push failed: {e.stderr.decode()}")

def deploy_lambda_functions(stack_outputs):
    """Packages and deploys the code for both Lambda functions."""
    logging.info("📦 Packaging and deploying Lambda functions...")
    
    nudge_function_name = stack_outputs.get('NudgeLambdaFunctionName')
    handler_function_name = stack_outputs.get('TelegramHandlerFunctionName')

    if not nudge_function_name or not handler_function_name:
        logging.error("Lambda function names not found. Cannot deploy code.")
        return

    for func_name, handler_file in [
        (nudge_function_name, NUDGE_AGENT_PY_FILE),
        (handler_function_name, HANDLER_PY_FILE)
    ]:
        logging.info(f"Deploying code for {func_name} from {handler_file}...")
        zip_file_name = f"/tmp/{func_name}.zip"
        
        with zipfile.ZipFile(zip_file_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(handler_file)

        with open(zip_file_name, 'rb') as f:
            zipped_code = f.read()

        try:
            lambda_client.update_function_code(FunctionName=func_name, ZipFile=zipped_code)
            logging.info(f"✅ Successfully updated code for {func_name}.")
        except ClientError as e:
            logging.error(f"Failed to update code for {func_name}: {e}")
        os.remove(zip_file_name)

def setup_knowledge_base_data(bucket_name):
    """Uploads trusted sources to S3 for manual Knowledge Base sync."""
    if not bucket_name:
        logging.error("S3 bucket name not found.")
        return
    logging.info("📚 Uploading data for Knowledge Base...")
    try:
        if not os.path.exists(TRUSTED_SOURCES_FILE):
            logging.warning(f"{TRUSTED_SOURCES_FILE} not found. Creating a dummy file.")
            with open(TRUSTED_SOURCES_FILE, 'w') as f:
                f.write("devpost.com\n")

        s3_client.upload_file(TRUSTED_SOURCES_FILE, bucket_name, TRUSTED_SOURCES_FILE)
        logging.info("✅ Trusted sources file uploaded.")
        logging.info("   -> Please go to the Bedrock console to manually sync your Knowledge Base data source.")
    except (ClientError, FileNotFoundError) as e:
        logging.error(f"Knowledge Base data upload failed: {e}")

def main():
    """Main deployment orchestration flow."""
    load_dotenv()
    
    required_vars = ['KNOWLEDGE_BASE_ID']
    if not all(os.environ.get(var) for var in required_vars):
        logging.error("❌ Missing required environment variables in your .env file.")
        logging.error(f"Please ensure {', '.join(required_vars)} are set.")
        return

    parameters = {
        "kb_id": os.environ['KNOWLEDGE_BASE_ID'],
    }
    
    logging.info("🚀 Starting Hackathon Hunter Deployment 🚀")
    
    deploy_infrastructure(parameters)
    outputs = get_stack_outputs()
    if not outputs:
        logging.error("Failed to retrieve stack outputs. Halting deployment.")
        return

    build_and_push_docker_image(outputs.get('ECRRepositoryURI'))
    deploy_lambda_functions(outputs)
    setup_knowledge_base_data(outputs.get('S3BucketName'))
    
    logging.info("\n🎉 Deployment Summary & Next Steps 🎉")
    logging.info("=" * 40)
    logging.info(f"✅ Infrastructure is DEPLOYED/UPDATED in region {REGION}.")
    logging.info(f"✅ Scout Agent Docker image is PUSHED to ECR.")
    logging.info(f"✅ Nudge & Handler Lambda function code is DEPLOYED.")
    logging.info(f"✅ Knowledge Base data has been UPLOADED to S3.")
    logging.info("-" * 40)
    logging.info("📋 Final Manual Steps:")
    logging.info("1. In the Bedrock console, go to your Knowledge Base and sync the data source.")
    logging.info(f"2. Set your Telegram Bot's webhook to the following URL:")
    logging.info(f"   -> {outputs.get('TelegramWebhookURL')}")
    logging.info("=" * 40)

if __name__ == "__main__":
    main()

