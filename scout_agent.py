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
# We now use http_request directly from strands_tools
from strands_tools import http_request, file_read, file_write, use_aws
from strands.models import BedrockModel

# --- Agent System Prompt (Rewritten) ---
SYSTEM_PROMPT = """You are the Scout Agent, an autonomous AI responsible for discovering hackathons. Your primary mission is to analyze websites, create tools to extract data, and report your progress. You must use the provided tools in a logical sequence.

Your thought process must be streamed back to the user. Before you perform any significant action (like checking a tool, analyzing HTML, or generating code), you MUST call the `report_progress` tool to inform the user what you are about to do.

**AGENT WORKFLOW:**

1.  **Check for Existing Tool:**
    * Call `report_progress("Checking for existing tool for <source_url>...")`
    * Call `check_existing_tool(source_url="<source_url>")`.

2.  **If Tool is NOT Found (Analyze and Build):**
    * Call `report_progress("No tool found. Fetching website content for analysis...")`
    * Call `http_request(url="<source_url>")` to get the raw HTML/JSON content.
    * Call `report_progress("Analyzing content to find an API or scraping strategy...")`
    * **YOU (the agent)** will now *directly analyze* the content from the `http_request`. Your goal is to find a hidden JSON API (like in `<script>` tags or JS variables).
    * **Based on your analysis, you must formulate a strategy JSON object.**
        * If API found: `{"api_found": true, "endpoint_url": "THE_URL", "method": "GET", "notes": "Found API endpoint X, seems to return JSON list of hackathons."}`
        * If no API: `{"api_found": false, "strategy": "Direct HTML scraping required. Hackathons are in <div> tags with class 'hackathon-card'."}`
    * Call `report_progress("Strategy formulated. Generating Python extraction tool...")`

3.  **Generate Extraction Tool (Code Generation):**
    * **YOU (the agent)** will now *directly write the Python code* for a function `extract_hackathons(url)`.
    * This function MUST import `requests` and `BeautifulSoup` (if scraping).
    * It must return a list of dictionaries, e.g., `[{"title": "...", "deadline": "...", "prize": "..."}]`.
    * **You must output ONLY the raw Python code for the function, wrapped in ```python ... ```.**
    * Call `report_progress("Code generated. Saving the new tool to the database...")`
    * Call `save_extraction_tool(source_url="<source_url>", tool_code="<THE PYTHON CODE YOU JUST WROTE>", strategy_json='<THE STRATEGY JSON YOU FORMULATED>')`.

4.  **Execute and Store:**
    * Call `report_progress("Executing the tool to extract data...")`
    * Call `execute_extraction_tool(source_url="<source_url>")`.
    * Call `report_progress("Storing extracted hackathon data...")`
    * Call `store_hackathon_data(hackathons_json="<result from execute_extraction_tool>")`.
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

    # --- DELETED `discover_api_or_scraper_strategy` ---
    # The agent will do this logic itself using `http_request` and its own reasoning

    # --- DELETED `generate_extraction_tool` ---
    # The agent will generate code itself and use the new `save_extraction_tool`

    # --- NEW TOOL ---
    @tool
    def save_extraction_tool(self, source_url: str, tool_code: str, strategy_json: str) -> str:
        """
        Saves a newly generated Python tool (as a string) to the Scraper Functions DynamoDB table.
        The agent must generate the code *first* and then pass it to this tool.
        """
        try:
            strategy = json.loads(strategy_json)
            
            # Clean up the code to remove markdown fences if the agent added them
            if "```python" in tool_code:
                tool_code = tool_code.split("```python")[1].split("```")[0].strip()
            
            table_name = os.environ['SCRAPER_FUNCTIONS_TABLE']
            dynamodb_client.put_item(
                TableName=table_name,
                Item={
                    'source_url': {'S': source_url},
                    'scraper_code': {'S': tool_code},
                    'function_type': {'S': 'api' if strategy.get("api_found") else 'scraper'},
                    'last_updated_timestamp': {'N': str(int(time.time()))}
                }
            )
            return f"SUCCESS: Generated and saved tool for {source_url}."
        except Exception as e:
            print(f"ERROR saving tool: {e}")
            return f"ERROR: Failed to save tool: {e}"
    
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
            print(f"ERROR executing tool: {e}")
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
            print(f"ERROR storing data: {e}")
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
            print(f"ERROR storing preferences: {e}")
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
            
            print(f"INFO: Initializing Scout Agent for chat_id: {chat_id}")
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
            print("INFO: Task completed successfully.")
            
        except Exception as e:
            print(f"FATAL_ERROR: {e}")
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