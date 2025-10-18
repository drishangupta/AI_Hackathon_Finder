"""
Nudge Agent - Proactive Notification Core
Lightweight agent for scheduled notifications via Telegram
"""

import boto3
import json
from typing import Dict, List
from strands import Agent, tool
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth


class NudgeAgent(Agent):
    def __init__(self):
        super().__init__(
            name="HackathonNudge",
            description="Sends personalized hackathon notifications based on user interests"
        )
        self.bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
        self.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        
        # Setup OpenSearch client with proper authentication
        session = boto3.Session()
        credentials = session.get_credentials()
        region = 'us-east-1'
        
        auth = AWS4Auth(credentials.access_key, credentials.secret_key, region, 'aoss', session_token=credentials.token)
        
        self.opensearch = OpenSearch(
            hosts=[{'host': 'your-collection-id.us-east-1.aoss.amazonaws.com', 'port': 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection
        )
    
    @tool
    def send_weekly_notifications(self) -> Dict:
        """Main scheduled task: analyze interests → craft notifications → send via Telegram"""
        users = self._get_active_users()
        notifications_sent = 0
        
        for user_id in users:
            notification = self._craft_personalized_notification(user_id)
            if notification:
                self._send_telegram_notification(user_id, notification)
                notifications_sent += 1
        
        return {"notifications_sent": notifications_sent, "users_processed": len(users)}
    
    def _get_active_users(self) -> List[str]:
        """Get users who have stored preferences"""
        response = self.opensearch.search(
            index='user-preferences',
            body={"query": {"match_all": {}}}
        )
        return [hit['_source']['user_id'] for hit in response['hits']['hits']]
    
    def _craft_personalized_notification(self, user_id: str) -> str:
        """Use Claude 3 Haiku to craft personalized notification text"""
        # Get user preferences
        user_prefs = self._get_user_preferences(user_id)
        
        # Get recent hackathons matching preferences
        matching_hackathons = self._find_matching_hackathons(user_id, user_prefs)
        
        if not matching_hackathons:
            return None
        
        # Useing Claude 3 Haiku for fast, efficient notification crafting
        prompt = f"""
        User preferences: {user_prefs['preference_text']}
        Matching hackathons: {json.dumps(matching_hackathons[:3])}
        
        Write a brief, engaging Telegram message about these opportunities.
        Keep it under 200 characters.
        """
        
        response = self.bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150
            })
        )
        
        result = json.loads(response['body'].read())
        return result['content'][0]['text']
    
    def _get_user_preferences(self, user_id: str) -> Dict:
        """Retrieve user preferences from OpenSearch"""
        response = self.opensearch.search(
            index='user-preferences',
            body={"query": {"term": {"user_id": user_id}}}
        )
        return response['hits']['hits'][0]['_source']
    
    def _find_matching_hackathons(self, user_id: str, user_prefs: Dict) -> List[Dict]:
        """Find hackathons matching user preferences using vector similarity"""
        # Vector similarity search in OpenSearch
        response = self.opensearch.search(
            index='hackathons',
            body={
                "query": {
                    "knn": {
                        "description_vector": {
                            "vector": user_prefs['preference_vector'],
                            "k": 5
                        }
                    }
                }
            }
        )
        return [hit['_source'] for hit in response['hits']['hits']]
    
    def _send_telegram_notification(self, user_id: str, message: str):
        """Send notification via Telegram Bot API"""
        # Implementation would use Telegram Bot API
        print(f"Sending to {user_id}: {message}")


# Lambda handler for scheduled execution
def lambda_handler(event, context):
    """AWS Lambda entry point for EventBridge Scheduler"""
    agent = NudgeAgent()
    result = agent.send_weekly_notifications()
    
    return {
        'statusCode': 200,
        'body': json.dumps(result)
    }
