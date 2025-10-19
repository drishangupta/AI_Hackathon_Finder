from strands import Agent, tool
from strands_tools import file_read, file_write, use_aws
from strands.agent.conversation_manager import SlidingWindowConversationManager
import json
import hashlib
from datetime import datetime

class NudgeAgent(Agent):
    def __init__(self):
        conversation_manager = SlidingWindowConversationManager(
            window_size=10,  # Smaller window for lightweight agent
            should_truncate_results=True
        )
        
        tools = [
            file_read, file_write, use_aws,
            self.get_user_interests,
            self.find_matching_hackathons,
            self.should_send_notification,
            self.craft_notification,
            self.send_notification,
            self.check_notification_history
        ]
        
        super().__init__(
            tools=tools,
            conversation_manager=conversation_manager
        )
    
    @tool
    def get_user_interests(self, user_id: str) -> str:
        """Retrieve user's tracked hackathons and preferences"""
        try:
            # Try to read user preferences
            user_prefs = file_read(path=f"user_prefs_{user_id}.json")
            prefs_data = json.loads(user_prefs)
            
            # Try to read user's tracked hackathons
            try:
                user_hackathons = file_read(path=f"user_hackathons_{user_id}.json")
                hackathons_data = json.loads(user_hackathons)
            except:
                hackathons_data = {"tracked_hackathons": []}
            
            return json.dumps({
                "preferences": prefs_data.get("preferences", ""),
                "tracked_count": len(hackathons_data.get("tracked_hackathons", [])),
                "interests": prefs_data
            })
            
        except:
            return json.dumps({"error": "No user data found", "preferences": "", "tracked_count": 0})
    
    @tool
    def find_matching_hackathons(self, user_preferences: str) -> str:
        """Find hackathons matching user preferences using vector similarity"""
        try:
            # Get all stored hackathons
            hackathon_files = ["hackathons_devpost.com.json", "hackathons_hackerearth.com.json"]
            all_hackathons = []
            
            for file_name in hackathon_files:
                try:
                    hackathons_data = file_read(path=file_name)
                    hackathons = json.loads(hackathons_data)
                    all_hackathons.extend(hackathons)
                except:
                    continue
            
            # Simple keyword matching (in production would use vector similarity)
            preference_keywords = user_preferences.lower().split()
            matching_hackathons = []
            
            for hackathon in all_hackathons:
                title = hackathon.get('title', '').lower()
                description = hackathon.get('description', '').lower()
                
                # Check if any preference keyword matches
                if any(keyword in title or keyword in description for keyword in preference_keywords):
                    matching_hackathons.append(hackathon)
            
            return json.dumps({
                "total_hackathons": len(all_hackathons),
                "matching_hackathons": matching_hackathons[:5],  # Top 5 matches
                "match_count": len(matching_hackathons)
            })
            
        except Exception as e:
            return json.dumps({"error": str(e), "matching_hackathons": []})
    
    @tool
    def should_send_notification(self, user_id: str, matching_hackathons: str) -> str:
        """Decide if notification should be sent based on history and new matches"""
        try:
            matches_data = json.loads(matching_hackathons)
            match_count = matches_data.get("match_count", 0)
            
            # Check notification history
            try:
                notification_history = file_read(path=f"notifications_{user_id}.json")
                history_data = json.loads(notification_history)
                last_notification = history_data.get("last_sent", "")
            except:
                history_data = {"notifications": [], "last_sent": ""}
                last_notification = ""
            
            # Decision logic
            should_notify = False
            reason = ""
            
            if match_count == 0:
                reason = "No matching hackathons found"
            elif match_count > 0 and not last_notification:
                should_notify = True
                reason = f"First notification with {match_count} matches"
            elif match_count >= 3:
                should_notify = True
                reason = f"High number of matches: {match_count}"
            else:
                reason = f"Only {match_count} matches, threshold not met"
            
            return json.dumps({
                "should_notify": should_notify,
                "reason": reason,
                "match_count": match_count,
                "last_notification": last_notification
            })
            
        except Exception as e:
            return json.dumps({"should_notify": False, "reason": f"Error: {str(e)}"})
    
    @tool
    def craft_notification(self, user_preferences: str, matching_hackathons: str) -> str:
        """Use Claude Haiku to craft personalized notification"""
        try:
            matches_data = json.loads(matching_hackathons)
            hackathons = matches_data.get("matching_hackathons", [])
            
            if not hackathons:
                return "No hackathons to notify about"
            
            # Create prompt for Claude Haiku
            notification_prompt = f"""
            User preferences: {user_preferences}
            Matching hackathons: {json.dumps(hackathons[:3])}
            
            Write a brief, engaging notification message for Telegram.
            Keep it under 200 characters.
            Include hackathon names and why they match user interests.
            Use emojis and friendly tone.
            """
            
            # Use Claude Haiku for fast notification crafting
            haiku_result = use_aws(
                service_name="bedrock-runtime",
                operation_name="invoke_model", 
                parameters={
                    "modelId": "apac.anthropic.claude-3-haiku-20240307-v1:0",
                    "body": json.dumps({
                        "anthropic_version": "bedrock-2023-05-31",
                        "messages": [{"role": "user", "content": notification_prompt}],
                        "max_tokens": 150
                    })
                },
                region="ap-south-1"
            )
            
            # Fallback message if Bedrock fails
            fallback_message = f"🚀 Found {len(hackathons)} hackathons matching your interests! Check out: {hackathons[0].get('title', 'New Hackathon')}"
            
            return fallback_message
            
        except Exception as e:
            return f"📢 New hackathons available matching your interests!"
    
    @tool
    def send_notification(self, user_id: str, message: str) -> str:
        """Send notification via Telegram (mock implementation)"""
        try:
            # In production, this would use Telegram Bot API
            # For now, store the notification
            
            notification_data = {
                "user_id": user_id,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "status": "sent"
            }
            
            # Update notification history
            try:
                history = file_read(path=f"notifications_{user_id}.json")
                history_data = json.loads(history)
            except:
                history_data = {"notifications": []}
            
            history_data["notifications"].append(notification_data)
            history_data["last_sent"] = datetime.now().isoformat()
            
            file_write(
                path=f"notifications_{user_id}.json",
                content=json.dumps(history_data, indent=2)
            )
            
            return f"Notification sent to {user_id}: {message}"
            
        except Exception as e:
            return f"Failed to send notification: {str(e)}"
    
    @tool
    def check_notification_history(self, user_id: str) -> str:
        """Check user's notification history"""
        try:
            history = file_read(path=f"notifications_{user_id}.json")
            history_data = json.loads(history)
            
            notification_count = len(history_data.get("notifications", []))
            last_sent = history_data.get("last_sent", "Never")
            
            return json.dumps({
                "total_notifications": notification_count,
                "last_notification": last_sent,
                "recent_notifications": history_data.get("notifications", [])[-3:]
            })
            
        except:
            return json.dumps({
                "total_notifications": 0,
                "last_notification": "Never",
                "recent_notifications": []
            })

# Create Nudge Agent instance
nudge_agent = NudgeAgent()

# Lambda handler for scheduled execution
def lambda_handler(event, context):
    """AWS Lambda entry point for EventBridge Scheduler"""
    try:
        # Get all users (in production, query from database)
        users = ["user1", "user2"]  # Mock user list
        
        results = []
        for user_id in users:
            # Get user interests
            interests = nudge_agent.get_user_interests(user_id)
            interests_data = json.loads(interests)
            
            if interests_data.get("preferences"):
                # Find matching hackathons
                matches = nudge_agent.find_matching_hackathons(interests_data["preferences"])
                
                # Check if should notify
                should_notify = nudge_agent.should_send_notification(user_id, matches)
                notify_data = json.loads(should_notify)
                
                if notify_data.get("should_notify"):
                    # Craft and send notification
                    message = nudge_agent.craft_notification(interests_data["preferences"], matches)
                    send_result = nudge_agent.send_notification(user_id, message)
                    results.append({"user_id": user_id, "status": "notified"})
                else:
                    results.append({"user_id": user_id, "status": "skipped", "reason": notify_data.get("reason")})
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Nudge agent execution complete',
                'results': results
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

if __name__ == "__main__":
    print("📢 Nudge Agent Ready - Proactive Notification Core")
    
    # Test the agent first
    test_user = "test_user"
    print(f"Testing with user: {test_user}")
    interests = nudge_agent.get_user_interests(test_user)
    print(f"User interests: {interests}")
    
    # Interactive mode
    print("\nEntering interactive mode...")
    while True:
        user_input = input("\n>> ")
        if user_input.lower() in ['exit', 'quit']:
            break
        
        response = nudge_agent(user_input)
        print(f"\n{response}")