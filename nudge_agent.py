import json
import boto3
import os
import logging
from datetime import datetime, timedelta, timezone

# --- Globals & Clients ---
REGION = os.environ.get("AWS_REGION", "ap-south-1")
dynamodb_client = boto3.client("dynamodb", region_name=REGION)
bedrock_client = boto3.client("bedrock-runtime", region_name=REGION)
sqs_client = boto3.client("sqs", region_name=REGION)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Environment Variables ---
USER_INTERESTS_TABLE = os.environ.get('USER_INTERESTS_TABLE')
HACKATHONS_TABLE = os.environ.get('HACKATHONS_TABLE')
NOTIFICATION_HISTORY_TABLE = os.environ.get('NOTIFICATION_HISTORY_TABLE')
RESPONSE_QUEUE_URL = os.environ.get('RESPONSE_QUEUE_URL') # SQS Queue for Telegram Bot
HAIKU_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0" # Ensure correct ID for your region

# --- Nudge Helper Class (No Strands Inheritance) ---
class NudgeHelper:

    # No __init__ needed unless passing clients

    # Removed @tool decorator
    def get_user_interests(self, user_id: str) -> str:
        """
        Retrieves the user's chat_id and details of all hackathons they are tracking from DynamoDB.
        Uses the user_id to query the UserInterestsTable.
        """
        logger.info(f"--- NUDGE: GETTING INTERESTS & TRACKED HACKATHONS --- for user_id: '{user_id}'")
        interests_table_name = USER_INTERESTS_TABLE
        tracked_hackathons_list = []
        chat_id = None

        if not interests_table_name:
            logger.warning("USER_INTERESTS_TABLE env var not set.")
            return json.dumps({"error": "Config error", "tracked_hackathons": [], "chat_id": None})

        try:
            response = dynamodb_client.query(
                TableName=interests_table_name,
                KeyConditionExpression="user_id = :uid",
                ExpressionAttributeValues={":uid": {'S': user_id}},
                ProjectionExpression="hackathon_id, hackathon_title, user_note, chat_id, tracked_timestamp"
            )
            items = response.get('Items', [])
            if items:
                for item in items:
                    if not chat_id:
                        chat_id = item.get('chat_id', {}).get('S')
                    hackathon_info = {
                        "hackathon_id": item.get('hackathon_id', {}).get('S', 'N/A'),
                        "title": item.get('hackathon_title', {}).get('S', 'N/A'),
                        "note": item.get('user_note', {}).get('S', None),
                        "tracked_timestamp": int(item.get('tracked_timestamp', {}).get('N', '0'))
                    }
                    tracked_hackathons_list.append(hackathon_info)
                logger.info(f"Found {len(tracked_hackathons_list)} tracked hackathons for user {user_id}")
                if not chat_id:
                    logger.warning(f"Could not retrieve chat_id from items for user {user_id}.")
            else:
                logger.info(f"No tracked hackathons found for {user_id}")
                # Potentially query a separate UserProfile table here for chat_id if no tracked items exist

        except Exception as e:
             logger.error(f"Error getting interests/tracked items from DynamoDB for {user_id}: {e}")
             return json.dumps({"error": f"DB Query Error: {str(e)}", "tracked_hackathons": [], "chat_id": None})

        return json.dumps({
            "tracked_hackathons": tracked_hackathons_list,
            "chat_id": chat_id
        })

    # Removed @tool
    def find_matching_hackathons(self, tracked_hackathons_json: str) -> str:
        """
        Finds RECENTLY ADDED hackathons from DynamoDB that are potentially SIMILAR
        to the hackathons the user is already tracking. Excludes already tracked ones.
        """
        logger.info(f"--- NUDGE: FINDING SIMILAR NEW HACKATHONS ---")
        hackathons_table_name = HACKATHONS_TABLE
        newly_matching_hackathons = []

        try:
            tracked_hackathons = json.loads(tracked_hackathons_json)
            if not isinstance(tracked_hackathons, list): raise ValueError("Input must be JSON list.")
            tracked_ids_set = {h.get('hackathon_id') for h in tracked_hackathons if h.get('hackathon_id')}
            tracked_titles = [h.get('title', '').lower() for h in tracked_hackathons if h.get('title')]
            tracked_keywords = set(word for title in tracked_titles for word in title.split() if len(word) > 3)
            logger.info(f"Using keywords from tracked hackathons: {tracked_keywords}")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Could not parse/validate tracked_hackathons_json: {e}")
            return json.dumps({"error": f"Invalid input: {e}", "matching_hackathons": []})

        if not hackathons_table_name:
            logger.error("HACKATHONS_TABLE env var not set.")
            return json.dumps({"error": "Config error", "matching_hackathons": []})

        try:
            seven_days_ago_ts = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
            paginator = dynamodb_client.get_paginator('scan')
            response_iterator = paginator.paginate(
                TableName=hackathons_table_name,
                FilterExpression="discovered_timestamp > :ts",
                ExpressionAttributeValues={":ts": {'N': str(seven_days_ago_ts)}},
                ProjectionExpression="hackathon_id, title, source_url, deadline, prize",
                Limit=100
            )
            all_recent_hackathons = []
            for page in response_iterator:
                for item in page.get('Items', []):
                    # Simplified parsing assuming all values are strings or numbers
                    hackathon = {k: v.get('S') or v.get('N') for k, v in item.items()}
                    if hackathon.get('hackathon_id') and hackathon.get('title'):
                        all_recent_hackathons.append(hackathon)
            logger.info(f"Scanned {len(all_recent_hackathons)} recent hackathons.")

            for h in all_recent_hackathons:
                if h['hackathon_id'] in tracked_ids_set: continue
                title_lower = h.get('title', '').lower()
                if tracked_keywords and any(keyword in title_lower for keyword in tracked_keywords):
                    newly_matching_hackathons.append(h)

            logger.info(f"Found {len(newly_matching_hackathons)} NEW similar hackathons.")
            top_new_matches = newly_matching_hackathons[:5]
            return json.dumps({"matching_hackathons": top_new_matches, "match_count": len(newly_matching_hackathons)})
        except Exception as e:
            logger.error(f"Error finding/filtering hackathons: {e}", exc_info=True)
            return json.dumps({"error": f"DB/Filter Error: {str(e)}", "matching_hackathons": []})

    # Removed @tool
    def should_send_notification(self, user_id: str, matching_hackathons_json: str) -> str:
        """
        Checks DynamoDB history, decides if notification needed, updates history if sending.
        """
        logger.info(f"--- NUDGE: DECIDING NOTIFICATION --- for user: {user_id}")
        notification_history_table_name = NOTIFICATION_HISTORY_TABLE
        try:
            matches_data = json.loads(matching_hackathons_json)
            new_match_count = matches_data.get("match_count", 0)
        except json.JSONDecodeError:
            logger.error(f"Could not parse matches JSON for {user_id}")
            return json.dumps({"should_notify": False, "reason": "Internal error"})

        if not notification_history_table_name:
            logger.warning("NOTIFICATION_HISTORY_TABLE env var not set.")
            should_notify = new_match_count > 0
            reason = "History table not config." + (" Proceeding." if should_notify else "")
            return json.dumps({"should_notify": should_notify, "reason": reason, "new_match_count": new_match_count})

        should_notify = False
        reason = ""
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        last_sent_timestamp = 0
        try:
            response = dynamodb_client.get_item(
                TableName=notification_history_table_name, Key={'user_id': {'S': user_id}}, ProjectionExpression="last_sent_timestamp"
            )
            if 'Item' in response: last_sent_timestamp = int(response['Item'].get('last_sent_timestamp', {}).get('N', '0'))
            else: logger.info(f"No history found for {user_id}.")
        except Exception as e:
            logger.error(f"Error getting history for {user_id}: {e}")
            reason += f" (Error reading history: {str(e)})" # Assume no history on error

        if new_match_count == 0: reason = "No new matches."; should_notify = False
        elif last_sent_timestamp == 0: reason = f"First notification ({new_match_count} matches)."; should_notify = True
        elif datetime.fromtimestamp(last_sent_timestamp, tz=timezone.utc) < seven_days_ago:
            reason = f"Notified >7 days ago. Sending for {new_match_count} new matches."; should_notify = True
        else: reason = f"Notified recently. Skipping for {new_match_count} new matches."; should_notify = False

        if should_notify:
            try:
                current_time_ts = int(datetime.now(timezone.utc).timestamp())
                dynamodb_client.update_item(
                    TableName=notification_history_table_name, Key={'user_id': {'S': user_id}},
                    UpdateExpression="SET last_sent_timestamp = :ts", ExpressionAttributeValues={":ts": {'N': str(current_time_ts)}}
                )
                logger.info(f"Updated history timestamp for {user_id}.")
            except Exception as e:
                logger.error(f"Error updating history for {user_id}: {e}")
                reason += f" (Warn: History update failed: {str(e)})"

        return json.dumps({"should_notify": should_notify, "reason": reason, "new_match_count": new_match_count})

    # Removed @tool
    def craft_notification(self, matching_hackathons_json: str) -> str:
        """Uses Bedrock Claude Haiku to craft a notification message."""
        logger.info(f"--- NUDGE: CRAFTING NOTIFICATION ---")
        try:
            matches_data = json.loads(matching_hackathons_json)
            hackathons = matches_data.get("matching_hackathons", [])
            if not hackathons: return ""

            details = [f"- {h.get('title', 'N/A')}" + (f" (Link: {h.get('source_url')})" if h.get('source_url') else "") for h in hackathons[:3]]
            prompt = f"Human: You're a friendly assistant finding relevant hackathons.\nFound these recently:\n{chr(10).join(details)}\n\nPlease write a brief, engaging Telegram notification (under 250 chars). Highlight 1-2 names, mention they're new/relevant. Use emojis like 🚀💡💻. Be excited!\n\nAssistant:"
            body = json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 100, "temperature": 0.7, "messages": [{"role": "user", "content": prompt}]})

            logger.info("Invoking Bedrock Haiku...")
            response = bedrock_client.invoke_model(body=body, modelId=HAIKU_MODEL_ID, accept='application/json', contentType='application/json')
            response_body = json.loads(response.get('body').read())

            content_blocks = response_body.get('content', [])
            if content_blocks and 'text' in content_blocks[0]:
                msg = content_blocks[0]['text'].strip()
                if msg and len(msg) > 10:
                    logger.info(f"Generated message: {msg}")
                    return msg
                else: logger.warning("Bedrock returned short/empty message.")
            else: logger.error(f"Could not parse text from Bedrock response: {response_body}")

            fallback = f"🚀 Found {len(hackathons)} new hackathons matching your interests! Check out: {hackathons[0].get('title', 'New Hackathon')}"
            return fallback
        except Exception as e:
            logger.error(f"Error crafting notification: {e}", exc_info=True)
            try: match_count = len(json.loads(matching_hackathons_json).get("matching_hackathons", [])) if matching_hackathons_json else "some"
            except: match_count = "some"
            return f"📢 Found {match_count} new hackathons matching your interests!"

    # Removed @tool
    def send_notification(self, chat_id: str, message: str, user_id: str = "Unknown") -> str:
         """Queues the notification message via SQS."""
         logger.info(f"--- NUDGE: QUEUING NOTIFICATION --- for chat_id: {chat_id} (User: {user_id})")
         response_queue_url = RESPONSE_QUEUE_URL
         if not response_queue_url: logger.error("SQS URL missing."); return "ERROR: Config error."
         if not chat_id: logger.error("chat_id missing."); return "ERROR: chat_id required."
         if not message: logger.warning(f"Empty message for {chat_id}. Skipping."); return "INFO: Empty message."

         try:
             payload = {'chat_id': chat_id, 'message': message}
             sqs_client.send_message(QueueUrl=response_queue_url, MessageBody=json.dumps(payload))
             logger.info(f"Queued message for chat_id {chat_id}")
             return f"SUCCESS: Queued for chat_id {chat_id}."
         except Exception as e:
             logger.error(f"Error queuing message for {chat_id}: {e}", exc_info=True)
             return f"ERROR: Failed to queue for {chat_id}: {str(e)}"

# --- Instantiate Helper Class (Globally) ---
nudge_helper = NudgeHelper()

# --- Lambda Handler (Uses Helper Class Instance) ---
def lambda_handler(event, context):
    """
    AWS Lambda entry point for scheduled nudge task. Uses NudgeHelper class.
    """
    logger.info("Starting Nudge Lambda execution...")
    # Check essential config
    required_env_vars = ['USER_INTERESTS_TABLE', 'HACKATHONS_TABLE', 'NOTIFICATION_HISTORY_TABLE', 'RESPONSE_QUEUE_URL']
    missing_vars = [var for var in required_env_vars if not globals().get(var)] # Check globals
    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.critical(error_msg)
        return {'statusCode': 500, 'body': json.dumps({'error': f'Configuration error: {error_msg}'})}

    users_to_process = []
    results = []
    # --- 1. Get User IDs ---
    try:
        paginator = dynamodb_client.get_paginator('scan')
        response_iterator = paginator.paginate(TableName=USER_INTERESTS_TABLE, ProjectionExpression="user_id")
        user_id_set = set(item.get('user_id', {}).get('S') for page in response_iterator for item in page.get('Items', []) if item.get('user_id', {}).get('S'))
        users_to_process = list(user_id_set)
        logger.info(f"Found {len(users_to_process)} unique users.")
    except Exception as e:
        logger.error(f"Failed to get users: {e}", exc_info=True)
        return {'statusCode': 500, 'body': json.dumps({'error': f'Failed to get users: {str(e)}'})}

    if not users_to_process:
        logger.info("No users found. Exiting.")
        return {'statusCode': 200, 'body': json.dumps({'message': 'No users to process'})}

    # --- 2. Process Each User ---
    for user_id in users_to_process:
        logger.info(f"Processing user: {user_id}")
        chat_id_for_user = None
        try:
            # --- a. Get Interests & Tracked Hackathons ---
            interests_json = nudge_helper.get_user_interests(user_id=user_id) # Use helper instance
            interests_data = json.loads(interests_json)
            if interests_data.get("error"):
                 results.append({"user_id": user_id, "status": "error_fetch_interests", "reason": interests_data['error']}); continue

            tracked_hackathons = interests_data.get("tracked_hackathons", [])
            chat_id_for_user = interests_data.get("chat_id")

            if not tracked_hackathons:
                results.append({"user_id": user_id, "status": "skipped", "reason": "No tracked items"}); continue
            if not chat_id_for_user:
                results.append({"user_id": user_id, "status": "skipped", "reason": "Missing chat_id"}); continue

            # --- b. Find Matching Hackathons ---
            matches_json = nudge_helper.find_matching_hackathons(tracked_hackathons_json=json.dumps(tracked_hackathons)) # Use helper instance
            matches_data = json.loads(matches_json)
            if matches_data.get("error"):
                 results.append({"user_id": user_id, "status": "error_find_matches", "reason": matches_data['error']}); continue

            # --- c. Decide if Notification is Needed ---
            should_notify_json = nudge_helper.should_send_notification(user_id=user_id, matching_hackathons_json=matches_json) # Use helper instance
            notify_data = json.loads(should_notify_json)

            # --- d. Craft and Send (If needed) ---
            if notify_data.get("should_notify"):
                logger.info(f"Notify {user_id}: {notify_data.get('reason')}")
                message = nudge_helper.craft_notification(matching_hackathons_json=matches_json) # Use helper instance
                if not message:
                     results.append({"user_id": user_id, "status": "skipped", "reason": "Crafted empty message"}); continue

                send_result = nudge_helper.send_notification(chat_id=chat_id_for_user, message=message, user_id=user_id) # Use helper instance
                status = "notified" if "SUCCESS" in send_result else "send_failed"
                results.append({"user_id": user_id, "chat_id": chat_id_for_user, "status": status, "reason": send_result if status=="send_failed" else None})
            else:
                logger.info(f"Skip {user_id}: {notify_data.get('reason')}")
                results.append({"user_id": user_id, "status": "skipped", "reason": notify_data.get("reason")})

        except Exception as e:
            logger.error(f"Critical error processing user {user_id}: {e}", exc_info=True)
            results.append({"user_id": user_id, "status": "error_processing_user", "reason": f"Unhandled exception: {str(e)}"})

    # --- 3. Return Overall Status ---
    logger.info("Nudge Lambda execution complete.")
    return {'statusCode': 200, 'body': json.dumps({'message': 'Nudge execution complete', 'results': results})}

# --- Optional: Local Testing ---
# (Keep __main__ block if needed, but it won't test the Lambda handler directly anymore)
# You would test by calling lambda_handler({}, {})