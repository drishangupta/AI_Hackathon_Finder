"""
Local testing for Scout and Nudge agents
"""

import json
from unittest.mock import Mock, patch
from scout_agent import ScoutAgent
from nudge_agent import NudgeAgent


def test_scout_agent():
    """Test Scout agent locally with mocked AWS services"""
    print("Testing Scout Agent...")
    
    with patch('boto3.client'), patch('boto3.resource'):
        agent = ScoutAgent()
        
        # Mock Bedrock responses
        agent.bedrock.invoke_model = Mock(return_value={
            'body': Mock(read=lambda: json.dumps({
                'content': [{'text': '''
def extract_hackathons(url):
    import requests
    from bs4 import BeautifulSoup
    
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    hackathons = []
    for item in soup.find_all('div', class_='hackathon-item'):
        hackathons.append({
            'title': item.find('h3').text,
            'date': item.find('.date').text,
            'url': url
        })
    return hackathons
                '''}]
            }).encode())
        })
        
        # Mock DynamoDB
        agent.dynamodb.Table = Mock(return_value=Mock(
            get_item=Mock(return_value={}),
            put_item=Mock()
        ))
        
        # Test discovery
        result = agent.discover_hackathons("AI and machine learning hackathons")
        print(f"Scout result: {result}")


def test_nudge_agent():
    """Test Nudge agent locally with mocked AWS services"""
    print("\nTesting Nudge Agent...")
    
    with patch('boto3.client'), patch('boto3.resource'):
        agent = NudgeAgent()
        
        # Mock OpenSearch responses
        agent.opensearch.search = Mock(return_value={
            'hits': {
                'hits': [
                    {'_source': {
                        'user_id': 'test_user', 
                        'preference_text': 'AI hackathons',
                        'preference_vector': [0.1] * 1536  # Mock 1536-dim vector
                    }}
                ]
            }
        })
        
        # Mock Bedrock for Haiku
        agent.bedrock.invoke_model = Mock(return_value={
            'body': Mock(read=lambda: json.dumps({
                'content': [{'text': '🚀 New AI hackathons match your interests! Check out DevPost for exciting opportunities.'}]
            }).encode())
        })
        
        # Test notifications
        result = agent.send_weekly_notifications()
        print(f"Nudge result: {result}")


if __name__ == "__main__":
    test_scout_agent()
    test_nudge_agent()
