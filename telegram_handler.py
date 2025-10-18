import json
import boto3
import os
from typing import Dict, Any

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Telegram webhook handler - routes messages to Scout/Nudge agents
    """
    try:
        # Parse Telegram webhook payload
        body = json.loads(event.get('body', '{}'))
        message = body.get('message', {})
        text = message.get('text', '')
        user_id = str(message.get('from', {}).get('id', ''))
        chat_id = message.get('chat', {}).get('id')
        
        if not text or not user_id:
            return {'statusCode': 200, 'body': json.dumps('OK')}
        
        # Route to appropriate agent based on intent
        if any(keyword in text.lower() for keyword in ['find', 'search', 'discover', 'look for']):
            # Route to Scout agent (ECS Fargate)
            response = trigger_scout_agent(text, user_id, chat_id)
        elif any(keyword in text.lower() for keyword in ['remind', 'notify', 'interested', 'preferences']):
            # Route to Nudge agent (Lambda)
            response = trigger_nudge_agent(text, user_id, chat_id)
        else:
            # Default to Scout for general queries
            response = trigger_scout_agent(text, user_id, chat_id)
        
        return {'statusCode': 200, 'body': json.dumps('OK')}
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps('Error')}

def trigger_scout_agent(message: str, user_id: str, chat_id: int) -> str:
    """Trigger Scout agent on ECS Fargate for complex discovery tasks"""
    ecs = boto3.client('ecs')
    
    try:
        # Send immediate response to user
        send_telegram_message(chat_id, "🔍 Analyzing... I'll find hackathons for you!")
        
        # Run Scout agent task
        response = ecs.run_task(
            cluster=os.environ['ECS_CLUSTER_NAME'],
            taskDefinition=os.environ['SCOUT_TASK_DEFINITION_ARN'],
            launchType='FARGATE',
            networkConfiguration={
                'awsvpcConfiguration': {
                    'subnets': [os.environ['SUBNET_A'], os.environ['SUBNET_B']],
                    'securityGroups': [os.environ['SECURITY_GROUP_ID']],
                    'assignPublicIp': 'ENABLED'
                }
            },
            overrides={
                'containerOverrides': [{
                    'name': 'scout-agent',
                    'environment': [
                        {'name': 'USER_MESSAGE', 'value': message},
                        {'name': 'USER_ID', 'value': user_id},
                        {'name': 'CHAT_ID', 'value': str(chat_id)},
                        {'name': 'KNOWLEDGE_BASE_ID', 'value': os.environ['KNOWLEDGE_BASE_ID']}
                    ]
                }]
            }
        )
        
        return f"Scout task started: {response['tasks'][0]['taskArn']}"
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error starting search: {str(e)}")
        return f"Error: {str(e)}"

def trigger_nudge_agent(message: str, user_id: str, chat_id: int) -> str:
    """Trigger Nudge agent Lambda for preference handling"""
    lambda_client = boto3.client('lambda')
    
    try:
        payload = {
            'message': message,
            'user_id': user_id,
            'chat_id': chat_id,
            'action': 'handle_preferences'
        }
        
        response = lambda_client.invoke(
            FunctionName='hackathon-nudge-agent',
            InvocationType='Event',  # Async
            Payload=json.dumps(payload)
        )
        
        send_telegram_message(chat_id, "✅ Got it! I'll remember your preferences.")
        return "Nudge agent triggered"
        
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Error saving preferences: {str(e)}")
        return f"Error: {str(e)}"

def send_telegram_message(chat_id: int, text: str):
    """Send message back to Telegram user"""
    import requests
    
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        print(f"No bot token - would send to {chat_id}: {text}")
        return
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={'chat_id': chat_id, 'text': text})
    except Exception as e:
        print(f"Failed to send message: {e}")