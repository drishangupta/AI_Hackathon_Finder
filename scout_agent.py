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
from strands.agent.conversation_manager import SummarizingConversationManager
# We now use http_request directly from strands_tools
from strands_tools import http_request, file_read, file_write, use_aws,shell
from strands.models import BedrockModel

logger = logging.getLogger()
logger.setLevel(logging.INFO)
os.environ["BYPASS_TOOL_CONSENT"] = "true"
# --- Agent System Prompt (Rewritten) ---
SYSTEM_PROMPT = """You are the Scout Agent, an autonomous AI with a persistent memory. You MUST follow this workflow for EVERY user message without deviation.

**Global Tool Error Handling Rule (Mandatory)**
You are equipped with a `shell` tool. If ANY tool call fails with a `ModuleNotFoundError: No module named 'X'`, you MUST NOT stop or apologize. Your next action MUST be to call the `shell` tool to run `pip install X`. After the installation is successful, 
you MUST immediately retry the original tool call that failed, and then continue the workflow.
**Global Rule**
    You should call report_progress tool to keep the user in loop of whatever you are doing, you MUST tell the user what you are doing every 10 seconds. User MUST NOT wait more than 30 seconds, if he must,you should tell him that the current task might take a bit
    If the user asks what hackathons they are currently tracking (e.g., "what am I tracking?", "show my tracked list"), you MUST call the `get_tracked_hackathons()` tool and report the result.
    If the user expresses explicit interest in a specific hackathon that was previously mentioned (e.g., "track that one," "remind me about X," "I'm interested in the AI challenge"), you MUST:
        1. Identify the unique `hackathon_id` and `title` of the hackathon they are referring to from the recent conversation context.
        2. Call the `track_hackathon(hackathon_id="<the_id>", hackathon_title="<the_title>")` tool.
        3. Confirm to the user that you are now tracking it.

**Step 0: Pre-Run Query Analysis (Mandatory Sanity Check)**
Your first thought MUST be to analyze the user's raw message.
- If the intent is `preference_update`, skip this step and go to Step 1.
- If the intent is `general_query` or `specific_url_check`:
    1.  Analyze its "freshness" and "feasibility." A query for "2026 hackathons" is for the distant future and likely has no results.
    2.  If the query seems unfeasible or for the distant future, you MUST NOT proceed to the main workflow.
    3.  Instead, your ONLY action will be to call the `http_request` tool ONCE to perform a single web search (e.g., http_request(url="https://www.google.com/search?q=<the user's original query text>")).
    4.  Analyze this single search result. If it confirms no data is available, you MUST report this to the user and then **STOP**.
    5.  Only if the query seems reasonable (e.g., "AI hackathons") OR your web search confirms results exist, you will state: 'Query is feasible. Proceeding to main workflow.' and then continue to Step 1.
    5.  Only if the search shows promise OR the query is for current data (e.g., "AI hackathons") should you proceed to Step 1.

**Step 1: Classify the User's Intent (Mandatory First Step)**
Your first thought MUST be to classify the user's message into one of three categories and state your choice. Your thought should be: 'The user's intent is [intent]. I will now proceed to Path [A/B/C].'
- `preference_update`: The user is asking you to remember something (e.g., "remember I like AI", "my interests are...").
- `general_query`: The user is asking a broad question (e.g., "find hackathons", "any new AI competitions?").
- `specific_url_check`: The user has provided a specific website URL to check (e.g., "check devpost.com").

**Step 2: Execute the Correct Path**

---
**Path A: Handle Preference Update**
If the intent is `preference_update`:
1. Call `report_progress("Updating user preferences in memory...")`.
2. Call store_user_preferences(preference_text="<the user's new preference>").
3. Then STOP. Your task is complete. Do not proceed to any other paths.

---
**Path B: Handle General Query**
If the intent is `general_query`:
1. Call `report_progress("Starting general query...")`.
2. **Your first action in this path MUST be to take the user's original message and call get_user_preferences() to load context.**
3. Call `report_progress("Getting list of trusted sources...")`.
4. Call `get_trusted_sources()`. This returns a list of URLs.
5. **Loop** through each URL from the list and follow the sub-workflow: "Process a Single URL".

---
**Path C: Handle Specific URL Check**
If the intent is `specific_url_check`:
1. Call `report_progress("Starting specific URL check...")`.
2. **Your first action in this path MUST be to take the user's original message and call get_user_preferences() to load context.**
3. Take the user's URL and follow the sub-workflow: "Process a Single URL".

---
**Sub-Workflow: Process a Single URL**
This workflow is called by Path B or C for each URL.

1.  **Check Cache:** Call `check_existing_tool(source_url="<the_current_url>")`.
2.  **Analyze Result:**
    * If `not_found`, go to `Discover and Save`.
    * If `scraper` found, go to `Execute Scraper`.
    * If `api` found, get the `endpoint_url` and go to `Execute API`.

3.  **Discover and Save:**
    * Call `http_request(url="<the_current_url>")` to get content.
    * **YOU** will analyze the content and formulate a strategy JSON (`{"api_found": ...}`).
    * If `api_found` is true, call `save_api_endpoint(...)` then go to `Execute API`.
    * If `api_found` is false, **YOU** will generate the Python scraper code, then call `save_extraction_tool(...)`, then go to `Execute Scraper`.
4.  **Execute API:** Call `http_request(url="<the_endpoint_url>")`. Proceed to `Store Data`.
5.  **Execute Scraper:**
    a. Call `execute_extraction_tool(source_url="<the_current_url>")`.
    b. **CRITICAL ERROR HANDLING:** If this call fails with a `ModuleNotFoundError: No module named 'X'`, you MUST follow the Global Error Handling Rule: immediately call the `shell` tool to run `pip install <module_name>`.
    c. After the shell tool succeeds, you MUST retry the `execute_extraction_tool` call from step 5a.
6.  **Store Data:** Call `store_hackathon_data(...)` with the results.
7.  **Loop or Finish:** If in a loop (Path B), move to the next URL. If all tasks are done, call `report_progress("✅ All tasks complete.")`.
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
    def __init__(self, chat_id, model,user_id):
        self.chat_id = chat_id
        self.user_id = user_id
        summary_model = BedrockModel(
                model_id="apac.anthropic.claude-3-haiku-20240307-v1:0",
                boto_session=session
            )
        summary_agent = Agent(model=summary_model,system_prompt="You are a summarizer. Condense this conversation. Retain all key user preferences, past tool outputs, URLs, and specific topics discussed. The goal is to create a context memo for another AI.")
        conversation_manager = SummarizingConversationManager(
            summary_ratio=0.4,
            summarization_agent=summary_agent
        )
        
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
            file_write,
            self.get_user_preferences,
            shell,
            self.track_hackathon,
            self.get_tracked_hackathons
        ]
        
        super().__init__(
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            conversation_manager=conversation_manager,
            model=model
            # We will let Strands pick the default model provider
            # which will be Bedrock based on the boto3 clients
        )
        self.load_history()
    
    
    def load_history(self):
        """Loads the conversation history from DynamoDB."""
        table_name = os.environ.get('CHAT_HISTORY_TABLE')
        if not table_name:
            logger.warning("CHAT_HISTORY_TABLE env var not set. Starting with no history.")
            return

        try:
            response = dynamodb_client.get_item(
                TableName=table_name,
                Key={'chat_id': {'S': self.chat_id}}
            )
            
            if 'Item' in response:
                # Load the messages list and assign it to the agent's memory
                messages_str = response['Item']['messages']['S']
                self.messages = json.loads(messages_str) # This is the key line
                logger.info(f"Loaded {len(self.messages)} messages from history for {self.chat_id}")
            else:
                logger.info(f"No chat history found for {self.chat_id}. Starting fresh.")
        
        except Exception as e:
            # Handle case where table or item doesn't exist yet
            if 'ResourceNotFoundException' in str(e):
                logger.warning(f"ChatHistory table not found. Starting with no history.")
            else:
                logger.error(f"Error loading history: {e}")

    def save_history(self):
        """Saves the current conversation history to DynamoDB."""
        table_name = os.environ.get('CHAT_HISTORY_TABLE')
        if not table_name:
            logger.warning("CHAT_HISTORY_TABLE env var not set. Cannot save history.")
            return

        try:
            # self.messages is the list of all messages managed by Strands.
            # We save the entire list (including the latest user/agent turn)
            # back to DynamoDB.
            messages_str = json.dumps(self.messages)
            
            dynamodb_client.put_item(
                TableName=table_name,
                Item={
                    'chat_id': {'S': self.chat_id},
                    'messages': {'S': messages_str},
                    'last_updated': {'N': str(int(time.time()))}
                }
            )
            logger.info(f"Saved {len(self.messages)} messages to history for {self.chat_id}")
        
        except Exception as e:
            logger.error(f"Error saving history: {e}")
    
    
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
    def track_hackathon(self, hackathon_id: str, hackathon_title: str, note: str = None) -> str:
        """
        Stores that the user is interested in a specific hackathon, including chat_id and an optional note.
        Uses user_id and hackathon_id as the primary key.
        Provide the hackathon_id and title. A brief note can optionally be added.
        """
        logger.info(f"--- TRACKING HACKATHON --- User: {self.user_id}, ChatID: {self.chat_id}, Hackathon ID: {hackathon_id}, Note: {note}")
        table_name = os.environ.get('USER_INTERESTS_TABLE')
        if not table_name:
            logger.error("USER_INTERESTS_TABLE env var not set. Cannot track hackathon.")
            return "ERROR: Configuration error, cannot track hackathon."

        try:
            item_to_put = {
                'user_id': {'S': self.user_id}, # HASH Key
                'hackathon_id': {'S': hackathon_id}, # RANGE Key
                'hackathon_title': {'S': hackathon_title},
                'chat_id': {'S': self.chat_id}, # Store chat_id
                'tracked_timestamp': {'N': str(int(time.time()))}
            }
            # Add the note only if provided by the user
            if note:
                item_to_put['user_note'] = {'S': note}

            # Use PutItem for HASH+RANGE key schema when creating/overwriting an item
            dynamodb_client.put_item(
                TableName=table_name,
                Item=item_to_put
            )
            logger.info(f"Successfully tracked hackathon {hackathon_id} for user {self.user_id}")
            response_message = f"SUCCESS: Now tracking '{hackathon_title}'."
            if note:
                response_message += f" Note added: '{note}'"
            return response_message

        except Exception as e:
            logger.error(f"Error tracking hackathon {hackathon_id} for user {self.user_id}: {e}", exc_info=True)
            return f"ERROR: Failed to track hackathon '{hackathon_title}': {str(e)}"
    
    @tool
    def get_tracked_hackathons(self) -> str:
        """
        Retrieves the list of hackathons (ID, title, note, tracked date)
        that the user is currently tracking.
        Use this when the user asks "what hackathons am I tracking?".
        """
        logger.info(f"--- GETTING TRACKED HACKATHONS --- for user: {self.user_id}")
        table_name = os.environ.get('USER_INTERESTS_TABLE')
        if not table_name:
            logger.error("USER_INTERESTS_TABLE env var not set. Cannot get tracked hackathons.")
            return "ERROR: Configuration error, cannot retrieve tracked hackathons."

        try:
            # Query for all items matching the user_id (partition key)
            response = dynamodb_client.query(
                TableName=table_name,
                KeyConditionExpression="user_id = :uid",
                ExpressionAttributeValues={
                    ":uid": {'S': self.user_id}
                },
                # Request specific attributes to retrieve
                ProjectionExpression="hackathon_id, hackathon_title, user_note, tracked_timestamp"
            )

            items = response.get('Items', [])

            if items:
                tracked_list = []
                for item in items:
                    hackathon_info = {
                        "id": item.get('hackathon_id', {}).get('S', 'N/A'),
                        "title": item.get('hackathon_title', {}).get('S', 'N/A'),
                        "note": item.get('user_note', {}).get('S', None), # Include the note
                        "tracked_since": int(item.get('tracked_timestamp', {}).get('N', '0')) # Include timestamp
                    }
                    tracked_list.append(hackathon_info)

                logger.info(f"Found {len(tracked_list)} tracked hackathons for user {self.user_id}")
                # Return a JSON list of dictionaries for clarity
                return f"SUCCESS: You are tracking the following hackathons: {json.dumps(tracked_list, indent=2)}"
            else:
                logger.info(f"User {self.user_id} is not tracking any hackathons.")
                return "INFO: You are not currently tracking any hackathons."

        except Exception as e:
            logger.error(f"Error getting tracked hackathons for user {self.user_id}: {e}", exc_info=True)
            return f"ERROR: Failed to retrieve tracked hackathons: {str(e)}"
    
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
                "BeautifulSoup": __import__("bs4", fromlist=["BeautifulSoup"]).BeautifulSoup,
                "selenium": __import__("selenium", fromlist=["webdriver"]).webdriver.ChromeOptions(),
                "json": __import__("json")
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
    def get_user_preferences(self) -> str:
        """
        Retrieves ALL stored preference texts for the user from OpenSearch
        and combines them into a single context string.
        (This version does NOT use vector search).
        """
        logger.info(f"--- GETTING ALL PREFERENCES --- for self.user_id: '{self.user_id}'")
        try:
            # Define the search query - get up to 100 docs, sort by time just in case
            search_body = {
                "size": 100,
                "query": {
                    "term": {
                        "user_id.keyword": self.user_id
                    }
                },
                "sort": [ # Optional: keeps order somewhat consistent
                    {"timestamp": {"order": "desc"}}
                ]
            }

            # Execute the search
            response = os_client.search(
                index='user_preferences',
                body=search_body
            )

            hits = response['hits']['hits']
            if hits:
                # Extract the preference text from ALL documents found
                all_prefs = []
                for hit in hits:
                    pref_text = hit['_source'].get('preference_text')
                    if pref_text:
                        all_prefs.append(pref_text.strip()) # Add strip() for cleanliness
                
                # Filter out empty strings just in case
                all_prefs = [pref for pref in all_prefs if pref]

                if all_prefs:
                    # Combine all non-empty preferences into a single string
                    combined_prefs = "; ".join(all_prefs)
                    logger.info(f"Retrieved combined preferences: {combined_prefs}")
                    return f"SUCCESS: Found user preferences: {combined_prefs}"

            # If no hits or no non-empty text in the hits
            logger.info(f"No preferences found for user {self.user_id}.")
            return "INFO: No preferences found for this user."

        except Exception as e:
            if 'index_not_found_exception' in str(e):
                 logger.info(f"Index 'user_preferences' not found. No preferences stored yet.")
                 return "INFO: No preferences found for this user."
            logger.error(f"ERROR retrieving user preferences: {e}", exc_info=True)
            return f"ERROR: Could not retrieve user preferences: {e}"
    
    @tool
    def store_user_preferences(self, preference_text: str) -> str:
        """
        Converts user preference text to an embedding and stores it in OpenSearch
        using the agent's internal user_id.
        """
        logger.info(f"--- STORING PREFERENCE --- for user_id: '{self.user_id}'")
        try:
            logger.info(f"--- STORING PREFERENCE --- for user_id: '{self.user_id}'")
            response = bedrock_client.invoke_model(
                modelId="amazon.titan-embed-text-v2:0",
                body=json.dumps({"inputText": preference_text})
            )
            embedding = json.loads(response['body'].read())['embedding']

            document = {
                'user_id': self.user_id,
                'preference_text': preference_text,
                'preference_vector': embedding,
                'timestamp': int(time.time())
            }
            os_client.index(
                index='user_preferences',
                body=document,
            )
            return f"SUCCESS: Preferences for user {self.user_id} have been stored."
        except Exception as e:
            logger.error(f"ERROR storing preferences: {e}")
            return f"ERROR: Failed to store preferences: {e}"



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
            agent = ScoutAgent(chat_id=chat_id, model=bedrock_model,user_id=user_id)
            final_response = agent(user_message)
            
            agent.save_history()            
            agent.report_progress(f"✅ Task Complete. Final summary: {final_response}")
            logger.info("INFO: Task completed successfully.")
            
        except Exception as e:
            logger.critical(f"FATAL_ERROR in ECS Mode: {e}", exc_info=True) # Add exc_info for traceback
            if 'chat_id' in locals():
                try:
                    # Just send a raw SQS message. It's safer.
                    response_queue_url = os.environ['RESPONSE_QUEUE_URL']
                    payload = {
                        'chat_id': chat_id,
                        'message': f"❌ A fatal error occurred: {str(e)}" # Send only string
                    }
                    sqs_client.send_message(
                        QueueUrl=response_queue_url,
                        MessageBody=json.dumps(payload)
                    )
                except Exception as report_e:
                    logger.error(f"Failed to report fatal error to user: {report_e}")
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