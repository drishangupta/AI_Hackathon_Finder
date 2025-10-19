import json
import boto3
import os
import requests
import logging

# Setup logging, which will go to CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    This function has two jobs, routed by the event structure:
    1. Handle incoming webhooks from Telegram (via API Gateway) to START a task.
    2. Handle incoming events from an SQS queue to SEND a response back to the user.
    """
    logger.info(f"Handler invoked with event: {json.dumps(event)}")

    # Check if the event is from SQS
    if 'Records' in event and event['Records'][0].get('eventSource') == 'aws:sqs':
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
            message = body.get('message', {})
            text = message.get('text', '')
            chat_id = message.get('chat', {}).get('id')

            if not text or not chat_id:
                logger.warning("Received a webhook with no text or chat_id. Ignoring.")
                return {'statusCode': 200, 'body': json.dumps('OK')}
            
            # Send an immediate acknowledgement to the user
            send_telegram_message(chat_id, "✅ Request received! The Scout Agent is on the case. I'll send you live updates as it makes progress...")

            ecs_client = boto3.client('ecs')
            
            # THE FIX IS HERE: Using .get() for safe, correct access to environment variables
            container_environment = [
                {'name': 'HACKATHONS_TABLE', 'value': os.environ.get('HACKATHONS_TABLE')},
                {'name': 'SCRAPER_FUNCTIONS_TABLE', 'value': os.environ.get('SCRAPER_FUNCTIONS_TABLE')},
                {'name': 'USER_INTERESTS_TABLE', 'value': os.environ.get('USER_INTERESTS_TABLE')},
                {'name': 'KNOWLEDGE_BASE_ID', 'value': os.environ.get('KNOWLEDGE_BASE_ID')},
                {'name': 'AWS_REGION', 'value': os.environ.get('AWS_REGION')},
                {'name': 'RESPONSE_QUEUE_URL', 'value': os.environ.get('RESPONSE_QUEUE_URL')},
                {'name': 'OPENSEARCH_ENDPOINT', 'value': os.environ.get('OPENSEARCH_ENDPOINT')},
                {'name': 'TELEGRAM_BOT_TOKEN', 'value': os.environ.get('TELEGRAM_BOT_TOKEN', '')},
                # Dynamic variables specific to this request
                {'name': 'USER_MESSAGE', 'value': text},
                {'name': 'CHAT_ID', 'value': str(chat_id)}
            ]

            logger.info(f"Invoking Scout Agent on ECS for chat_id {chat_id}...")
            # Asynchronously trigger the Scout Agent on ECS
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
            return {'statusCode': 200, 'body': json.dumps('OK')}
        except Exception as e:
            logger.error(f"FATAL_ERROR in handler processing webhook: {e}")
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