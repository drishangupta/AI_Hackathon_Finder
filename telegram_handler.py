import json
import boto3
import os
import requests
import logging
import time # <-- Import time
from botocore.exceptions import ClientError # <-- Import ClientError

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize DynamoDB client (outside handler for reuse)
dynamodb_client = boto3.client('dynamodb')
PROCESSED_MESSAGES_TABLE_NAME = os.environ.get('PROCESSED_MESSAGES_TABLE') # Get table name from env var
TTL_SECONDS = 600 # 10 minutes TTL

def lambda_handler(event, context):
    """
    Handles Telegram webhooks and SQS messages. Includes idempotency check for webhooks.
    """
    logger.info(f"Handler invoked with event: {json.dumps(event)}")

    # Check if the event is from SQS
    if 'Records' in event and event['Records'][0].get('eventSource') == 'aws:sqs':
        # ... (Your existing SQS handling code - no changes needed here) ...
        for record in event['Records']:
            try:
                payload = json.loads(record['body'])
                chat_id = payload.get('chat_id')
                message = payload.get('message')
                if chat_id and message:
                    logger.info(f"Sending SQS message to chat_id {chat_id}: {message}")
                    send_telegram_message(chat_id, message)
            except Exception as e:
                logger.error(f"ERROR: Could not process SQS record: {e}")
        return {'statusCode': 200}

    # Otherwise, assume it's an API Gateway (Telegram webhook) event
    else:
        try:
            body = json.loads(event.get('body', '{}'))
            message_obj = body.get('message', {})
            text = message_obj.get('text', '')
            chat_id = message_obj.get('chat', {}).get('id')
            message_id = message_obj.get('message_id') # Get the unique message ID

            if not text or not chat_id or not message_id:
                logger.warning("Received webhook missing text, chat_id, or message_id. Ignoring.")
                return {'statusCode': 200, 'body': json.dumps('OK')}

            # --- IDEMPOTENCY CHECK ---
            if PROCESSED_MESSAGES_TABLE_NAME:
                current_time = int(time.time())
                ttl_timestamp = current_time + TTL_SECONDS

                try:
                    dynamodb_client.put_item(
                        TableName=PROCESSED_MESSAGES_TABLE_NAME,
                        Item={
                            'message_id': {'S': str(message_id)}, # Primary Key
                            'received_timestamp': {'N': str(current_time)},
                            'ttl_timestamp': {'N': str(ttl_timestamp)} # TTL attribute
                        },
                        ConditionExpression='attribute_not_exists(message_id)' # Only succeed if ID is new
                    )
                    logger.info(f"First time processing message_id: {message_id}")
                except ClientError as e:
                    if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                        logger.warning(f"Duplicate message_id received: {message_id}. Ignoring.")
                        return {'statusCode': 200, 'body': json.dumps('Already processed')}
                    else:
                        # Handle other potential DynamoDB errors
                        logger.error(f"DynamoDB error during idempotency check: {e}")
                        # Optionally, decide if you want to proceed or fail here
                        # For safety, we'll fail if we can't be sure about idempotency
                        return {'statusCode': 500, 'body': json.dumps('Error checking message uniqueness')}
            else:
                logger.warning("PROCESSED_MESSAGES_TABLE environment variable not set. Skipping idempotency check.")
            # --- END IDEMPOTENCY CHECK ---

            # Send immediate acknowledgement (Only if it's the first time)
            send_telegram_message(chat_id, "✅ Request received! The Scout Agent is on the case. I'll send you live updates...")

            ecs_client = boto3.client('ecs')

            # ... (Your existing code to prepare container_environment) ...
            container_environment = [
                 # ... (your existing env vars like HACKATHONS_TABLE etc.)
                 {'name': 'USER_MESSAGE', 'value': text},
                 {'name': 'CHAT_ID', 'value': str(chat_id)}
            ]

            logger.info(f"Invoking Scout Agent on ECS for chat_id {chat_id}, message_id {message_id}...")
            # Asynchronously trigger the Scout Agent on ECS
            ecs_client.run_task(
                 # ... (your existing run_task configuration) ...
                 cluster=os.environ.get('ECS_CLUSTER_NAME'),
                 taskDefinition=os.environ.get('SCOUT_TASK_DEFINITION_ARN'),
                 launchType='FARGATE',
                 networkConfiguration={
                     'awsvpcConfiguration': {
                         'subnets': [os.environ.get('SUBNET_A'), os.environ.get('SUBNET_B')],
                         'securityGroups': [os.environ.get('SECURITY_GROUP_ID')],
                         'assignPublicIp': 'ENABLED'
                     }
                 },
                 overrides={
                     'containerOverrides': [{
                         'name': 'scout-agent',
                         'environment': container_environment
                     }]
                 }
            )
            return {'statusCode': 200, 'body': json.dumps('Task started')}

        except Exception as e:
            logger.error(f"FATAL_ERROR in handler processing webhook: {e}", exc_info=True) # Add traceback
            # Try to inform the user about the failure if possible
            if 'chat_id' in locals():
                try:
                    send_telegram_message(chat_id, f"❌ Sorry, there was an internal error processing your request: {str(e)}")
                except:
                    pass # Avoid errors during error reporting
            return {'statusCode': 500, 'body': json.dumps('Error processing webhook')}

def send_telegram_message(chat_id, text):
    # ... (Your existing send_telegram_message function - no changes needed) ...
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Cannot send message.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown' # Or 'HTML' if you prefer
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not send Telegram message: {e}")