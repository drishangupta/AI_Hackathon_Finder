import json
import boto3
import os
import requests
import logging
from collections import deque

# --- SETUP: IN-MEMORY IDEMPOTENCY CACHE ---
# This cache will persist between invocations on a warm Lambda container.
# We use a deque as a fixed-size queue to prevent memory leaks.
PROCESSED_IDS = deque(maxlen=100) # Remember the last 100 update_ids

# Setup logging, which will go to CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def is_update_already_processed(update_id):
    """Checks the in-memory deque if this update_id has been seen recently."""
    if update_id in PROCESSED_IDS:
        logger.warning(f"Duplicate update_id detected in memory cache: {update_id}. Ignoring.")
        return True
    PROCESSED_IDS.append(update_id)
    logger.info(f"First time processing update_id: {update_id}. Adding to cache.")
    return False

def lambda_handler(event, context):
    """
    Handles Telegram webhooks and SQS messages, with in-memory idempotency for webhooks.
    """
    logger.info(f"Handler invoked with event: {json.dumps(event)}")

    # SQS Event Processing (for receiving results from the Scout agent)
    if 'Records' in event and event['Records'][0].get('eventSource') == 'aws:sqs':
        for record in event['Records']:
            try:
                payload = json.loads(record['body'])
                chat_id = payload.get('chat_id')
                message = payload.get('message')
                if chat_id and message:
                    send_telegram_message(chat_id, message)
            except Exception as e:
                logger.error(f"ERROR: Could not process SQS record: {e}")
        return {'statusCode': 200}
    
    # API Gateway (Telegram Webhook) Event Processing
    else:
        try:
            body = json.loads(event.get('body', '{}'))
            update_id = body.get('update_id')
            message = body.get('message', {})
            text = message.get('text', '')
            chat_id = message.get('chat', {}).get('id')

            # --- THE FIX: IDEMPOTENCY CHECK ---
            if not update_id:
                 logger.warning("Webhook did not contain an update_id. Cannot guarantee idempotency.")
            elif is_update_already_processed(update_id):
                 # If it's a duplicate, just return OK immediately to stop the retry loop.
                 return {'statusCode': 200, 'body': json.dumps('OK (Duplicate)')}

            # --- Proceed only if it is NOT a duplicate ---
            if not text or not chat_id:
                logger.warning("Ignoring webhook with no text or chat_id.")
                return {'statusCode': 200, 'body': json.dumps('OK')}
            
            # Send the (now single) acknowledgement to the user
            send_telegram_message(chat_id, "✅ Request received! The Scout Agent is on the case. I'll send you live updates as it makes progress...")

            ecs_client = boto3.client('ecs')
            
            container_environment = [
                 {'name': 'HACKATHONS_TABLE', 'value': os.environ.get('HACKATHONS_TABLE')},
                 {'name': 'SCRAPER_FUNCTIONS_TABLE', 'value': os.environ.get('SCRAPER_FUNCTIONS_TABLE')},
                 {'name': 'USER_INTERESTS_TABLE', 'value': os.environ.get('USER_INTERESTS_TABLE')},
                 {'name': 'KNOWLEDGE_BASE_ID', 'value': os.environ.get('KNOWLEDGE_BASE_ID')},
                 {'name': 'AWS_REGION', 'value': os.environ.get('AWS_REGION')},
                 {'name': 'RESPONSE_QUEUE_URL', 'value': os.environ.get('RESPONSE_QUEUE_URL')},
                 {'name': 'OPENSEARCH_ENDPOINT', 'value': os.environ.get('OPENSEARCH_ENDPOINT')},
                 {'name': 'TELEGRAM_BOT_TOKEN', 'value': os.environ.get('TELEGRAM_BOT_TOKEN', '')},
                 {'name': 'USER_MESSAGE', 'value': text},
                 {'name': 'CHAT_ID', 'value': str(chat_id)}
            ]

            logger.info(f"Invoking Scout Agent on ECS for update_id {update_id}, chat_id {chat_id}...")
            ecs_client.run_task(
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
            return {'statusCode': 200, 'body': json.dumps('OK (Processing)')}
        except Exception as e:
            logger.error(f"FATAL_ERROR in handler processing webhook: {e}", exc_info=True)
            return {'statusCode': 500, 'body': json.dumps('Error processing webhook')}

def send_telegram_message(chat_id, text):
    """Sends a message to a Telegram chat."""
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Cannot send message.")
        return
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except requests.exceptions.RequestException as e:
        logger.warning(f"Could not send Telegram message: {e}")

