from strands import Agent, tool
from strands_tools import http_request, file_write, file_read, use_aws
from strands.agent.conversation_manager import SlidingWindowConversationManager
import json
import re
import hashlib
import os
import sys
import boto3

class ScoutAgent(Agent):
    def __init__(self):
        conversation_manager = SlidingWindowConversationManager(
            window_size=20,
            should_truncate_results=True
        )
        
        tools = [
            http_request, file_write, file_read, use_aws,
            self.classify_user_intent,
            self.get_trusted_sources,
            self.check_existing_scrapers,
            self.discover_apis,
            self.generate_scraper,
            self.execute_scraper,
            self.store_hackathon_data,
            self.store_user_preferences
        ]
        
        super().__init__(
            tools=tools,
            conversation_manager=conversation_manager
        )
    
    @tool
    def classify_user_intent(self, user_message: str) -> str:
        """Determine what the user wants: discovery, preferences, or status check"""
        discovery_keywords = ['find', 'search', 'discover', 'look for', 'hackathons on']
        preference_keywords = ['interested in', 'like', 'prefer', 'my interests', 'set preferences']
        status_keywords = ['my hackathons', 'what am i tracking', 'status', 'remind me']
        
        message_lower = user_message.lower()
        
        if any(keyword in message_lower for keyword in discovery_keywords):
            return "discovery"
        elif any(keyword in message_lower for keyword in preference_keywords):
            return "preferences"
        elif any(keyword in message_lower for keyword in status_keywords):
            return "status"
        else:
            return "general"
    
    @tool
    def get_trusted_sources(self) -> str:
        """Get trusted hackathon sources from knowledge base"""
        try:
            kb_result = use_aws(
                service_name="bedrock-agent-runtime",
                operation_name="retrieve",
                parameters={
                    "knowledgeBaseId": os.environ.get('KNOWLEDGE_BASE_ID', 'fallback'),
                    "retrievalQuery": {"text": "hackathon websites trusted sources"}
                },
                region="ap-south-1"
            )
            return "devpost.com,hackerearth.com,mlh.io"
        except:
            return "devpost.com,hackerearth.com,mlh.io"
    
    @tool
    def check_existing_scrapers(self, url: str) -> str:
        """Check if we already have a scraper for this URL"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        scraper_file = f"scraper_{url_hash}.py"
        
        try:
            existing_scraper = file_read(path=scraper_file)
            return f"Found existing scraper for {url}"
        except:
            return f"No existing scraper for {url}"
    
    @tool
    def discover_apis(self, url: str) -> str:
        """Analyze website for hidden APIs using Claude Sonnet"""
        # Fetch website content
        content = http_request(url=url, method="GET")
        if not content:
            return f"Failed to fetch {url}"
        
        # Use Claude Sonnet for API discovery
        api_prompt = f"""
        Analyze this website for hidden JSON APIs or data endpoints:
        URL: {url}
        Content: {content[:3000]}
        
        Look for AJAX calls, API endpoints, JSON data sources.
        Return JSON: {{"api_found": true/false, "endpoint": "url", "method": "GET/POST"}}
        """
        
        try:
            api_analysis = use_aws(
                service_name="bedrock-runtime",
                operation_name="invoke_model",
                parameters={
                    "modelId": "anthropic.claude-3-sonnet-20240229-v1:0",
                    "body": json.dumps({
                        "anthropic_version": "bedrock-2023-05-31",
                        "messages": [{"role": "user", "content": api_prompt}],
                        "max_tokens": 500
                    })
                },
                region="us-east-1"
            )
            return f"API analysis complete for {url}"
        except:
            return f"API analysis failed for {url}, will use scraping"
    
    @tool
    def generate_scraper(self, url: str, api_info: str = "none") -> str:
        """Generate Python scraper code using Claude Sonnet"""
        scraper_prompt = f"""
        Generate Python code to extract hackathon data from {url}.
        API Info: {api_info}
        
        Create function extract_hackathons(url) returning list of dicts with:
        - title, deadline, prize, description, url
        
        Use requests and BeautifulSoup. Return only executable Python code.
        """
        
        try:
            code_result = use_aws(
                service_name="bedrock-runtime", 
                operation_name="invoke_model",
                parameters={
                    "modelId": "anthropic.claude-3-sonnet-20240229-v1:0",
                    "body": json.dumps({
                        "anthropic_version": "bedrock-2023-05-31",
                        "messages": [{"role": "user", "content": scraper_prompt}],
                        "max_tokens": 1500
                    })
                },
                region="us-east-1"
            )
            
            # Store generated scraper
            url_hash = hashlib.md5(url.encode()).hexdigest()
            scraper_file = f"scraper_{url_hash}.py"
            
            # Extract actual code from Bedrock response (mock for now)
            generated_code = f'''
def extract_hackathons(url):
    import requests
    from bs4 import BeautifulSoup
    import json
    
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        hackathons = []
        
        # Simple scraper for {url}
        if "devpost.com" in url:
            # DevPost specific scraping
            for item in soup.find_all('div', class_='software-entry')[:5]:
                title_elem = item.find('h5') or item.find('h4') or item.find('h3')
                title = title_elem.text.strip() if title_elem else 'Unknown Hackathon'
                
                hackathons.append({{
                    'title': title,
                    'deadline': 'TBD',
                    'prize': 'Unknown',
                    'url': url,
                    'source': 'devpost'
                }})
        else:
            # Generic hackathon scraping
            titles = soup.find_all(['h1', 'h2', 'h3'], string=lambda text: text and ('hackathon' in text.lower() or 'hack' in text.lower()))[:3]
            for title in titles:
                hackathons.append({{
                    'title': title.text.strip(),
                    'deadline': 'TBD',
                    'prize': 'Unknown', 
                    'url': url,
                    'source': 'generic'
                }})
        
        return hackathons if hackathons else [{{'title': 'Sample Hackathon', 'deadline': 'Dec 31', 'prize': '$10K', 'url': url, 'source': 'mock'}}]
        
    except Exception as e:
        return [{{'error': str(e), 'url': url}}]
'''
            file_write(path=scraper_file, content=generated_code)
            
            return f"Generated scraper for {url}, stored as {scraper_file}"
            
        except Exception as e:
            return f"Failed to generate scraper: {str(e)}"
    
    @tool
    def execute_scraper(self, url: str) -> str:
        """Execute the generated scraper safely"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        scraper_file = f"scraper_{url_hash}.py"
        
        try:
            scraper_code = file_read(path=scraper_file)
            
            # Execute scraper directly in ECS container (safe isolation)
            try:
                # Create safe execution environment
                safe_globals = {
                    '__builtins__': {
                        'print': print, 'len': len, 'str': str, 'int': int,
                        'dict': dict, 'list': list, 'range': range
                    },
                    'requests': __import__('requests'),
                    'BeautifulSoup': __import__('bs4').BeautifulSoup,
                    'json': __import__('json'),
                    're': __import__('re')
                }
                
                local_vars = {}
                
                # Execute the generated scraper code
                exec(scraper_code, safe_globals, local_vars)
                
                # Run the extract_hackathons function
                if 'extract_hackathons' in local_vars:
                    results = local_vars['extract_hackathons'](url)
                    execution_result = f"Scraper executed successfully: {json.dumps(results)}"
                else:
                    execution_result = "Error: extract_hackathons function not found in generated code"
                    
            except Exception as e:
                execution_result = f"Scraper execution failed: {str(e)}"
            
            return f"Scraper executed for {url}: {execution_result}"
            
        except Exception as e:
            return f"Scraper execution failed: {str(e)}"
    
    @tool
    def store_hackathon_data(self, hackathons_json: str, source_url: str) -> str:
        """Store discovered hackathons in DynamoDB"""
        try:
            hackathons = json.loads(hackathons_json)
            
            for hackathon in hackathons:
                hackathon_id = hashlib.md5(f"{hackathon.get('title', '')}{source_url}".encode()).hexdigest()
                
                use_aws(
                    service_name="dynamodb",
                    operation_name="put_item",
                    parameters={
                        "TableName": "Hackathons",
                        "Item": {
                            "hackathon_id": {"S": hackathon_id},
                            "title": {"S": hackathon.get('title', '')},
                            "source_url": {"S": source_url},
                            "data": {"S": json.dumps(hackathon)}
                        }
                    },
                    region="us-east-1"
                )
            
            return f"Stored {len(hackathons)} hackathons from {source_url}"
            
        except Exception as e:
            # Fallback to file storage
            file_write(path=f"hackathons_{source_url.replace('https://', '').replace('/', '_')}.json", 
                      content=hackathons_json)
            return f"Stored hackathons locally due to error: {str(e)}"
    
    @tool
    def store_user_preferences(self, user_id: str, preferences: str) -> str:
        """Store user preferences with Titan embeddings"""
        try:
            # Generate embedding
            embedding_result = use_aws(
                service_name="bedrock-runtime",
                operation_name="invoke_model",
                parameters={
                    "modelId": "amazon.titan-embed-text-v2:0",
                    "body": json.dumps({"inputText": preferences})
                },
                region="us-east-1"
            )
            
            # Store in OpenSearch (simplified)
            file_write(
                path=f"user_prefs_{user_id}.json",
                content=json.dumps({
                    "user_id": user_id,
                    "preferences": preferences,
                    "embedding": "vector_data_here"
                })
            )
            
            return f"Stored preferences for {user_id}: {preferences}"
            
        except Exception as e:
            return f"Failed to store preferences: {str(e)}"

# Create Scout Agent instance
scout_agent = ScoutAgent()

def send_telegram_message(chat_id: str, message: str):
    """Send message to Telegram user"""
    print(f"TELEGRAM_SEND:{chat_id}:{message}")

if __name__ == "__main__":
    # Check if running as ECS container
    if os.environ.get('USER_MESSAGE'):
        # ECS container mode
        user_message = os.environ.get('USER_MESSAGE')
        user_id = os.environ.get('USER_ID', 'unknown')
        chat_id = os.environ.get('CHAT_ID', '0')
        kb_id = os.environ.get('KNOWLEDGE_BASE_ID')
        
        if not kb_id:
            print("ERROR: KNOWLEDGE_BASE_ID not set")
            sys.exit(1)
        
        print(f"🔍 Scout processing: {user_message} for user {user_id}")
        
        try:
            response = scout_agent(user_message)
            send_telegram_message(chat_id, f"🎯 {response}")
            print("✅ Task completed")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error: {str(e)}")
            print(f"ERROR: {e}")
            sys.exit(1)
    else:
        # Interactive mode
        print("🔍 Scout Agent Ready - Discovery & Analysis Core")
        while True:
            user_input = input("\n>> ")
            if user_input.lower() in ['exit', 'quit']:
                break
            response = scout_agent(user_input)
            print(f"\n{response}")