import json
import boto3
import os
import sys
import hashlib
import time
import re
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager

# --- Agent System Prompt ---
SYSTEM_PROMPT = """You are the Scout Agent, an autonomous AI responsible for discovering hackathons. Your primary mission is to analyze websites, create tools to extract data, and report your progress. You must use the provided tools in a logical sequence.

Your thought process must be streamed back to the user. Before you perform any significant action (like checking for a tool, generating code, or executing a tool), you MUST call the `report_progress` tool to inform the user what you are about to do.

Example workflow:
1. User asks to find hackathons on "newsite.com".
2. You think: "First, I need to report that I'm checking for an existing tool for this site." -> Call `report_progress("Checking for an existing tool for newsite.com...")`
3. You think: "Now I will actually check." -> Call `check_existing_tool("newsite.com")`
4. Tool not found. You think: "Okay, no tool exists. I need to discover the best way to get data. I'll report this." -> Call `report_progress("No tool found. Analyzing website to discover the best data extraction strategy...")`
5. You think: "Now I'll analyze the site." -> Call `discover_api_or_scraper_strategy("newsite.com")`
6. And so on for generating, executing, and storing data. Always report before you act.
"""

# --- Boto3 Clients (initialized once) ---
REGION = os.environ.get("AWS_REGION", "ap-south-1")
bedrock_client = boto3.client("bedrock-runtime", region_name=REGION)
dynamodb_client = boto3.client("dynamodb", region_name=REGION)
kb_client = boto3.client("bedrock-agent-runtime", region_name=REGION)
sqs_client = boto3.client("sqs", region_name=REGION)
credentials = boto3.Session().get_credentials()
aws_auth = AWS4Auth(credentials.access_key, credentials.secret_key, REGION, 'aoss', session_token=credentials.token)

# --- OpenSearch Client ---
OPENSEARCH_ENDPOINT = os.environ.get("OPENSEARCH_ENDPOINT", "")
if not OPENSEARCH_ENDPOINT.startswith('https://'):
    OPENSEARCH_ENDPOINT = f'https://{OPENSEARCH_ENDPOINT}'

os_client = OpenSearch(
    hosts=[{'host': OPENSEARCH_ENDPOINT.replace('https://',''), 'port': 443}],
    http_auth=aws_auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)

class ScoutAgent(Agent):
    def __init__(self, chat_id):
        self.chat_id = chat_id
        conversation_manager = SlidingWindowConversationManager(window_size=20)
        
        tools = [
            self.report_progress,
            self.get_trusted_sources,
            self.check_existing_tool,
            self.discover_api_or_scraper_strategy,
            self.generate_extraction_tool,
            self.execute_extraction_tool,
            self.store_hackathon_data,
            self.store_user_preferences
        ]
        
        super().__init__(
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            conversation_manager=conversation_manager
        )

    @tool
    def report_progress(self, message: str) -> str:
        """Reports the agent's current status or next action to the user."""
        try:
            response_queue_url = os.environ['RESPONSE_QUEUE_URL']
            payload = {
                'chat_id': self.chat_id,
                'message': f"⚙️ Agent status: {message}"
            }
            sqs_client.send_message(
                QueueUrl=response_queue_url,
                MessageBody=json.dumps(payload)
            )
            return "Progress reported to the user."
        except Exception as e:
            print(f"ERROR reporting progress: {e}")
            return "Failed to report progress."

    @tool
    def get_trusted_sources(self) -> str:
        """Gets a list of trusted hackathon websites from the Bedrock Knowledge Base."""
        try:
            kb_id = os.environ['KNOWLEDGE_BASE_ID']
            response = kb_client.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": "list of trusted hackathon websites"}
            )
            sources = [result['content']['text'] for result in response['retrievalResults']]
            return "\n".join(sources)
        except Exception as e:
            print(f"ERROR getting trusted sources: {e}")
            return "Failed to retrieve trusted sources. Using fallback: devpost.com"

    @tool
    def check_existing_tool(self, source_url: str) -> str:
        """Checks if a data extraction tool already exists for a given URL in DynamoDB."""
        try:
            table_name = os.environ['SCRAPER_FUNCTIONS_TABLE']
            response = dynamodb_client.get_item(
                TableName=table_name,
                Key={'source_url': {'S': source_url}}
            )
            if 'Item' in response:
                return f"SUCCESS: Found existing tool for {source_url}."
            else:
                return f"INFO: No existing tool found for {source_url}."
        except Exception as e:
            print(f"ERROR checking for existing tool: {e}")
            return f"ERROR: Could not check for existing tool: {e}"

    @tool
    def discover_api_or_scraper_strategy(self, source_url: str) -> str:
        """Analyzes a website's source to find a hidden API or determine a scraping strategy."""
        try:
            import requests
            html_content = requests.get(source_url, timeout=10).text
            # Basic sanitization
            clean_html = re.sub(r'<style.*?</style>', '', html_content, flags=re.DOTALL)
            clean_html = re.sub(r'<script.*?</script>', '', clean_html, flags=re.DOTALL)
            
            prompt = f"""
            You are an expert reverse-engineer. Analyze the following HTML from {source_url}.
            Your goal is to find a hidden JSON API endpoint. Look for fetch calls, API URLs, or inline JSON.
            If you find a usable API, respond with a JSON object: {{"api_found": true, "endpoint_url": "THE_URL", "method": "GET/POST", "notes": "Describe how to use it"}}
            If you DO NOT find a usable API, respond with: {{"api_found": false, "strategy": "Direct HTML scraping required due to static content."}}
            
            HTML Content (first 5000 chars):
            {clean_html[:5000]}
            """
            
            response = bedrock_client.converse(
                modelId="anthropic.claude-3-sonnet-20240229-v1:0",
                messages=[{"role": "user", "content": prompt}],
                inferenceConfig={"maxTokens": 500}
            )
            result = response['output']['message']['content'][0]['text']
            return result
        except Exception as e:
            print(f"ERROR discovering strategy: {e}")
            return json.dumps({"api_found": False, "strategy": f"Failed to analyze URL, fallback to scraping: {e}"})
    
    @tool
    def generate_extraction_tool(self, source_url: str, strategy_json: str) -> str:
        """Generates a Python function to extract hackathon data based on the discovered strategy."""
        try:
            strategy = json.loads(strategy_json)
            prompt = ""
            if strategy.get("api_found"):
                prompt = f"""
                Act as an expert Python developer. Based on the discovered API for {source_url}: {strategy_json},
                write a complete Python function `extract_hackathons(url)` that uses the `requests` library to call this endpoint, 
                parse the JSON response, and return a list of dictionaries. Each dictionary must contain 'title', 'deadline', and 'prize'.
                Return ONLY the raw Python code.
                """
            else:
                import requests
                html_content = requests.get(source_url, timeout=10).text
                prompt = f"""
                Act as an expert Python developer specializing in web scraping. Since no API was found for {source_url}, 
                analyze the provided HTML and write a complete Python function `extract_hackathons(url)` using `requests` and `BeautifulSoup` 
                to extract the hackathon data directly. Each returned dictionary must contain 'title', 'deadline', and 'prize'.
                Return ONLY the raw Python code.

                HTML Content (first 5000 chars):
                {html_content[:5000]}
                """

            response = bedrock_client.converse(
                modelId="anthropic.claude-3-sonnet-20240229-v1:0",
                messages=[{"role": "user", "content": prompt}],
                inferenceConfig={"maxTokens": 2000}
            )
            generated_code = response['output']['message']['content'][0]['text']
            
            # Clean up the response to get only the code
            if "```python" in generated_code:
                generated_code = generated_code.split("```python")[1].split("```")[0]

            # Store the generated function in DynamoDB
            table_name = os.environ['SCRAPER_FUNCTIONS_TABLE']
            dynamodb_client.put_item(
                TableName=table_name,
                Item={
                    'source_url': {'S': source_url},
                    'scraper_code': {'S': generated_code},
                    'function_type': {'S': 'api' if strategy.get("api_found") else 'scraper'},
                    'last_updated_timestamp': {'N': str(int(time.time()))}
                }
            )
            return f"SUCCESS: Generated and saved tool for {source_url}."
        except Exception as e:
            print(f"ERROR generating tool: {e}")
            return f"ERROR: Failed to generate tool: {e}"

    @tool
    def execute_extraction_tool(self, source_url: str) -> str:
        """Executes a generated tool to extract hackathon data."""
        try:
            table_name = os.environ['SCRAPER_FUNCTIONS_TABLE']
            response = dynamodb_client.get_item(
                TableName=table_name,
                Key={'source_url': {'S': source_url}}
            )
            if 'Item' not in response:
                return f"ERROR: No tool found for {source_url}. Please generate one first."
            
            scraper_code = response['Item']['scraper_code']['S']
            
            local_scope = {}
            exec(scraper_code, globals(), local_scope)
            
            hackathons = local_scope['extract_hackathons'](source_url)
            
            # Robustly check if the output is a list of dicts
            if isinstance(hackathons, list) and all(isinstance(i, dict) for i in hackathons):
                return json.dumps(hackathons)
            else:
                 return json.dumps([{"error": "Scraper did not return a valid list of dictionaries."}])

        except Exception as e:
            print(f"ERROR executing tool: {e}")
            return json.dumps([{"error": f"Failed to execute tool: {e}"}])

    @tool
    def store_hackathon_data(self, hackathons_json: str) -> str:
        """Stores a list of hackathon data into the Hackathons DynamoDB table."""
        try:
            hackathons = json.loads(hackathons_json)
            # Handle potential nested structure like {"hackathons": [...]}
            if isinstance(hackathons, dict) and 'hackathons' in hackathons:
                hackathons = hackathons['hackathons']

            if not isinstance(hackathons, list):
                return "ERROR: Input is not a valid list of hackathons."

            table_name = os.environ['HACKATHONS_TABLE']
            table = boto3.resource('dynamodb', region_name=REGION).Table(table_name)
            
            with table.batch_writer() as batch:
                for hackathon in hackathons:
                    if not isinstance(hackathon, dict) or 'title' not in hackathon:
                        continue
                    
                    hackathon_id = hashlib.md5(f"{hackathon.get('title', '')}{hackathon.get('url', '')}".encode()).hexdigest()
                    batch.put_item(Item={
                        'hackathon_id': hackathon_id,
                        'title': hackathon.get('title', 'N/A'),
                        'deadline': hackathon.get('deadline', 'N/A'),
                        'prize': hackathon.get('prize', 'N/A'),
                        'source_url': hackathon.get('url', 'N/A'),
                        'discovered_timestamp': int(time.time()),
                        'raw_data_blob': json.dumps(hackathon)
                    })
            return f"SUCCESS: Stored {len(hackathons)} hackathons."
        except Exception as e:
            print(f"ERROR storing data: {e}")
            return f"ERROR: Failed to store hackathon data: {e}"

    @tool
    def store_user_preferences(self, user_id: str, preference_text: str) -> str:
        """Converts user preferences to an embedding and stores it in OpenSearch."""
        try:
            # 1. Generate embedding using Bedrock
            response = bedrock_client.invoke_model(
                modelId="amazon.titan-embed-text-v1",
                body=json.dumps({"inputText": preference_text})
            )
            embedding = json.loads(response['body'].read())['embedding']

            # 2. Store in OpenSearch
            document = {
                'user_id': user_id,
                'preference_text': preference_text,
                'preference_vector': embedding,
                'timestamp': int(time.time())
            }
            os_client.index(
                index='user_preferences',
                body=document,
                id=user_id, # Use user_id as document ID to allow updates
                refresh=True
            )
            return f"SUCCESS: Preferences for user {user_id} have been stored."
        except Exception as e:
            print(f"ERROR storing preferences: {e}")
            return f"ERROR: Failed to store preferences: {e}"


# --- Main Execution Logic ---
if __name__ == "__main__":
    if 'USER_MESSAGE' in os.environ:
        # ECS Container Mode
        try:
            user_message = os.environ['USER_MESSAGE']
            chat_id = os.environ['CHAT_ID']
            user_id = hashlib.md5(chat_id.encode()).hexdigest() # Create a stable user_id from chat_id
            
            print(f"INFO: Initializing Scout Agent for chat_id: {chat_id}")
            agent = ScoutAgent(chat_id=chat_id)
            
            final_response = agent(user_message)
            
            agent.report_progress(f"✅ Task Complete. Final summary: {final_response}")
            print("INFO: Task completed successfully.")
            
        except Exception as e:
            print(f"FATAL_ERROR: {e}")
            # Try to report the final error back to the user
            if 'chat_id' in locals():
                try:
                    ScoutAgent(chat_id=chat_id).report_progress(f"❌ A fatal error occurred: {e}")
                except:
                    pass
            sys.exit(1)
            
    else:
        # Interactive Local Mode
        print("--- Scout Agent Interactive Mode ---")
        chat_id = "local_user"
        agent = ScoutAgent(chat_id=chat_id)
        while True:
            try:
                user_input = input(">> ")
                if user_input.lower() in ['exit', 'quit']:
                    break
                response = agent(user_input)
                print(f"\nAGENT: {response}")
            except KeyboardInterrupt:
                print("\nExiting.")
                break

