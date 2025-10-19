import json
import boto3
import os
import sys
import hashlib
import time
import re
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import logging
from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
# We now use http_request directly from strands_tools
from strands_tools import http_request, file_read, file_write, use_aws
from strands.models import BedrockModel

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Agent System Prompt (Rewritten) ---
SYSTEM_PROMPT = """You are the Scout Agent, an autonomous AI responsible for discovering hackathons. Your primary mission is to analyze websites, create tools, and extract data. You must be as efficient as possible.

Your thought process must be streamed back to the user. Before you act, you MUST call `report_progress` to inform the user.

**AGENT WORKFLOW:**

1.  **Check for Existing Discovery:**
    * Call `report_progress("Checking for existing tool or API for <source_url>...")`
    * Call `check_existing_tool(source_url="<source_url>")`. This tool will return a JSON string.
    * **Analyze the JSON result:**
        * `{"status": "not_found"}`: Proceed to Step 2 (Discovery).
        * `{"status": "found", "type": "scraper"}`: Proceed to Step 4 (Execute Scraper).
        * `{"status": "found", "type": "api", "details": {...}}`: Get the `endpoint_url` from `details` and proceed to Step 3 (Execute API).

2.  **If NOT Found (Discover and Save):**
    * Call `report_progress("No existing discovery. Fetching website content for analysis...")`
    * Call `http_request(url="<source_url>")` to get the raw HTML/JSON.
    * Call `report_progress("Analyzing content to find an API or scraping strategy...")`
    * **YOU (the agent)** will now *directly analyze* the content.
    * **Based on your analysis, you must formulate a strategy JSON object:**
        * `{"api_found": true, "endpoint_url": "THE_URL", "method": "GET"}`
        * `{"api_found": false, "strategy": "Direct HTML scraping required."}`

    * **--- DECISION ---**
    * **IF `api_found` is `true`:**
        * Call `report_progress("Found a direct API. Saving endpoint...")`
        * Call `save_api_endpoint(source_url="<source_url>", strategy_json='<THE STRATEGY JSON YOU FORMULATED>')`.
        * Get the `endpoint_url` from the strategy and proceed to Step 3 (Execute API).

    * **IF `api_found` is `false`:**
        * Call `report_progress("API not found. Generating Python scraping tool...")`
        * **YOU (the agent)** will write a Python function `extract_hackathons(url)` using `requests` and `BeautifulSoup`.
        * It MUST return a list of dictionaries, e.g., `[{"title": "...", "deadline": "...", "prize": "..."}]`.
        * Call `report_progress("Code generated. Saving the new scraping tool...")`
        * Call `save_extraction_tool(source_url="<source_url>", tool_code="<THE PYTHON CODE YOU WROTE>", strategy_json='<THE STRATEGY JSON YOU FORMULATED>')`.
        * Proceed to Step 4 (Execute Scraper).

3.  **Execute API (If API exists):**
    * Call `report_progress("Executing via direct API call...")`
    * Call `http_request(url="<the endpoint_url>", method="GET")`.
    * The result will be a JSON string of hackathons.
    * Proceed to Step 5 (Store Data).

4.  **Execute Scraper (If Scraper exists):**
    * Call `report_progress("Executing via saved scraping tool...")`
    * Call `execute_extraction_tool(source_url="<source_url>")`.
    * The result will be a JSON string of hackathons.
    * Proceed to Step 5 (Store Data).

5.  **Store Data:**
    * Call `report_progress("Storing extracted hackathon data...")`
    * Call `store_hackathon_data(hackathons_json="<the JSON string from Step 3 or 4>")`.
    * Call `report_progress("✅ All tasks complete.")`
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
    def __init__(self, chat_id, model):
        self.chat_id = chat_id
        conversation_manager = SlidingWindowConversationManager(window_size=20)
        
        # --- Tool List (Rewritten) ---
        tools = [
            self.report_progress,
            self.get_trusted_sources,
            self.check_existing_tool,
            # We now use the http_request tool from strands_tools
            http_request,
            # This is our new, "simple" tool that just saves the code
            self.save_extraction_tool,
            self.execute_extraction_tool,
            self.store_hackathon_data,
            self.store_user_preferences,
            self.save_api_endpoint,
            file_read,
            file_write
        ]
        
        super().__init__(
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            conversation_manager=conversation_manager,
            model=model
            # We will let Strands pick the default model provider
            # which will be Bedrock based on the boto3 clients
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
            logger.error(f"ERROR reporting progress: {e}")
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
            logger.error(f"ERROR getting trusted sources: {e}")
            return "Failed to retrieve trusted sources. Using fallback: devpost.com"

    @tool
    def check_existing_tool(self, source_url: str) -> str:
        """
        Checks if a data extraction tool or API endpoint already exists for a given URL.
        Returns JSON describing what was found.
        """
        try:
            table_name = os.environ['SCRAPER_FUNCTIONS_TABLE']
            response = dynamodb_client.get_item(
                TableName=table_name,
                Key={'source_url': {'S': source_url}}
            )
            
            if 'Item' not in response:
                logger.info(f"No existing tool found for {source_url}.")
                return json.dumps({"status": "not_found"})

            item = response['Item']
            function_type = item.get('function_type', {}).get('S')

            if function_type == 'scraper':
                logger.info(f"Found existing 'scraper' tool for {source_url}.")
                return json.dumps({"status": "found", "type": "scraper"})
            
            elif function_type == 'api_endpoint':
                api_details_str = item.get('api_details', {}).get('S', '{}')
                logger.info(f"Found existing 'api_endpoint' for {source_url}.")
                return json.dumps({
                    "status": "found", 
                    "type": "api", 
                    "details": json.loads(api_details_str)
                })
            
            else:
                logger.warning(f"Found item for {source_url} but with unknown type: {function_type}")
                return json.dumps({"status": "not_found"})

        except Exception as e:
            logger.error(f"ERROR checking for existing tool: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    # --- DELETED `discover_api_or_scraper_strategy` ---
    # The agent will do this logic itself using `http_request` and its own reasoning

    # --- DELETED `generate_extraction_tool` ---
    # The agent will generate code itself and use the new `save_extraction_tool`

    # --- NEW TOOL ---
    
    @tool
    def save_api_endpoint(self, source_url: str, strategy_json: str) -> str:
        """
        Saves a discovered API endpoint (as a JSON string) to the Scraper Functions DynamoDB table.
        Use this when an API is found, instead of generating code.
        """
        try:
            strategy = json.loads(strategy_json)
            if not strategy.get("api_found"):
                return "ERROR: This tool is only for saving API endpoints. strategy_json must have 'api_found': true."

            table_name = os.environ['SCRAPER_FUNCTIONS_TABLE']
            dynamodb_client.put_item(
                TableName=table_name,
                Item={
                    'source_url': {'S': source_url},
                    'api_details': {'S': strategy_json},
                    'function_type': {'S': 'api_endpoint'},
                    'last_updated_timestamp': {'N': str(int(time.time()))}
                }
            )
            logger.info(f"SUCCESS: Saved API endpoint for {source_url}.")
            return f"SUCCESS: Saved API endpoint for {source_url}."
        except Exception as e:
            logger.error(f"ERROR saving API endpoint: {e}")
            return f"ERROR: Failed to save API endpoint: {e}"
    
    
    @tool
    def save_extraction_tool(self, source_url: str, tool_code: str, strategy_json: str) -> str:
        """
        Saves a newly generated Python *scraping* tool to the Scraper Functions DynamoDB table.
        Use this ONLY when a scraper function is generated (i.e., api_found is false).
        """
        try:
            strategy = json.loads(strategy_json)
            if strategy.get("api_found"):
                return "ERROR: This tool is for saving scrapers. Use 'save_api_endpoint' for APIs."

            # Clean up the code to remove markdown fences
            if "```python" in tool_code:
                tool_code = tool_code.split("```python")[1].split("```")[0].strip()
            
            table_name = os.environ['SCRAPER_FUNCTIONS_TABLE']
            dynamodb_client.put_item(
                TableName=table_name,
                Item={
                    'source_url': {'S': source_url},
                    'scraper_code': {'S': tool_code},
                    'strategy_details': {'S': strategy_json}, # Store the strategy too
                    'function_type': {'S': 'scraper'}, # Explicitly 'scraper'
                    'last_updated_timestamp': {'N': str(int(time.time()))}
                }
            )
            logger.info(f"SUCCESS: Generated and saved scraping tool for {source_url}.")
            return f"SUCCESS: Generated and saved scraping tool for {source_url}."
        except Exception as e:
            logger.error(f"ERROR saving extraction tool: {e}")
            return f"ERROR: Failed to save extraction tool: {e}"
    
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
            
            # Import necessary libraries for the exec scope
            exec_globals = {
                "requests": __import__("requests"),
                "BeautifulSoup": __import__("bs4", fromlist=["BeautifulSoup"]).BeautifulSoup
            }
            local_scope = {}
            exec(scraper_code, exec_globals, local_scope)
            
            hackathons = local_scope['extract_hackathons'](source_url)
            
            if isinstance(hackathons, list) and all(isinstance(i, dict) for i in hackathons):
                return json.dumps(hackathons)
            else:
                return json.dumps([{"error": "Scraper did not return a valid list of dictionaries."}])

        except Exception as e:
            logger.error(f"ERROR executing tool: {e}")
            return json.dumps([{"error": f"Failed to execute tool: {e}"}])

    @tool
    def store_hackathon_data(self, hackathons_json: str) -> str:
        """Stores a list of hackathon data into the Hackathons DynamoDB table."""
        try:
            hackathons = json.loads(hackathons_json)
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
            logger.error(f"ERROR storing data: {e}")
            return f"ERROR: Failed to store hackathon data: {e}"

    @tool
    def store_user_preferences(self, user_id: str, preference_text: str) -> str:
        """Converts user preferences to an embedding and stores it in OpenSearch."""
        try:
            response = bedrock_client.invoke_model(
                modelId="amazon.titan-embed-text-v1",
                body=json.dumps({"inputText": preference_text})
            )
            embedding = json.loads(response['body'].read())['embedding']

            document = {
                'user_id': user_id,
                'preference_text': preference_text,
                'preference_vector': embedding,
                'timestamp': int(time.time())
            }
            os_client.index(
                index='user_preferences',
                body=document,
                id=user_id,
                refresh=True
            )
            return f"SUCCESS: Preferences for user {user_id} have been stored."
        except Exception as e:
            logger.error(f"ERROR storing preferences: {e}")
            return f"ERROR: Failed to store preferences: {e}"


# --- Main Execution Logic (Unchanged) ---
# This part is correct. It's the entry point for the ECS container.
if __name__ == "__main__":
    if 'USER_MESSAGE' in os.environ:
        # ECS Container Mode
        try:
            user_message = os.environ['USER_MESSAGE']
            chat_id = os.environ['CHAT_ID']
            user_id = hashlib.md5(chat_id.encode()).hexdigest()
            
            logger.info(f"INFO: Initializing Scout Agent for chat_id: {chat_id}")
            # We must configure the agent to use Bedrock
            # This is automatically handled by Strands if boto3 is configured
            # but we'll explicitly set the model for clarity.
            session = boto3.Session(region_name=os.environ.get("AWS_REGION", "ap-south-1"))

            # Create the Bedrock model instance
            bedrock_model = BedrockModel(
                model_id="apac.anthropic.claude-sonnet-4-20250514-v1:0",
                boto_session=session
            )

            # Pass the model object during initialization
            agent = ScoutAgent(chat_id=chat_id, model=bedrock_model)
            final_response = agent(user_message)
            
            agent.report_progress(f"✅ Task Complete. Final summary: {final_response}")
            logger.info("INFO: Task completed successfully.")
            
        except Exception as e:
            logger.critical(f"FATAL_ERROR: {e}")
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
        # agent.set_model("anthropic.claude-sonnet-4-20250514-v1:0")
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