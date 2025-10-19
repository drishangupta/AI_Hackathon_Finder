# Hackathon Hunter 🎯

**Multi-Agent AI System for Autonomous Hackathon Discovery**

## The Problem
Finding relevant hackathons is a manual, time-consuming process scattered across multiple platforms with no intelligent filtering or proactive notifications.

## The Solution
**Hackathon Hunter** - A 3-brain AI system that autonomously discovers, analyzes, and tracks hackathons using advanced tool generation and multi-agent architecture.

## 🚀 Core WOW Factor: Autonomous Tool Generation
The system **reverse-engineers websites in real-time** to create custom scrapers:
1. **API Archaeologist**: Analyzes website source code to find hidden JSON endpoints
2. **Code Generator**: Creates Python functions tailored to each site's structure  
3. **Safe Executor**: Runs generated code in isolated containers

## 🧠 3-Brain Architecture

### Brain 1: Scout Agent (Claude Sonnet + ECS Fargate)
- **Purpose**: Complex discovery and analysis
- **Tools**: API discovery, scraper generation, data extraction
- **Infrastructure**: ECS Fargate for long-running tasks

### Brain 2: Nudge Agent (Claude Haiku + Lambda)  
- **Purpose**: Intelligent notifications and reminders
- **Tools**: Interest matching, notification timing, user preferences
- **Infrastructure**: Lambda + EventBridge for scheduled execution

### Brain 3: Knowledge Base (Bedrock KB + S3)
- **Purpose**: Grounding with trusted sources
- **Content**: Curated hackathon platforms and API patterns
- **Function**: Prevents hallucination, ensures reliable discovery

## 🏗️ Tech Stack

### AWS Services
- **Amazon Bedrock**: Claude 3 Sonnet/Haiku, Titan Embeddings, Knowledge Base
- **ECS Fargate**: Scout agent container orchestration
- **AWS Lambda**: Nudge agent and Telegram webhook handler
- **DynamoDB**: Hackathon data and scraper function storage
- **OpenSearch Serverless**: Vector storage for user preferences
- **API Gateway**: Telegram webhook endpoint
- **EventBridge**: Scheduled notification triggers
- **ECR**: Docker image registry for Scout agent

### Framework & Libraries
- **Strands SDK**: Conversational AI agent framework
- **Python**: Core implementation language
- **Docker**: Containerized execution environment
- **Telegram Bot API**: User interface

## 📋 Database Schema

### DynamoDB Tables
```
Hackathons: hackathon_id (PK) → title, deadline, prize, source_url, data
ScraperFunctions: source_url (PK) → scraper_code, function_type, last_updated  
UserInterests: user_id (PK), hackathon_id (SK) → interest_level, timestamp
```

### OpenSearch Collection
```
user-preferences: user_id, preference_text, preference_vector (1536-dim)
```

## 🚀 Deployment

### 1. Infrastructure Setup
```bash
python deploy.py
```

### 2. Build & Push Docker Image
```bash
# Get ECR login
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker build -t hackathon-scout ./executor/
docker tag hackathon-scout:latest <ecr-uri>:latest
docker push <ecr-uri>:latest
```

### 3. Setup Knowledge Base
1. Upload `trusted_sources.txt` to S3 bucket
2. Create data source in Bedrock console
3. Sync Knowledge Base

### 4. Configure Telegram Bot
```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=<API_GATEWAY_URL>/webhook"
```

## 🎯 Usage Examples

### Discovery
```
User: "Find AI hackathons on DevPost"
Scout: 🔍 Analyzing DevPost for the first time...
Scout: 🛠️ Generated custom scraper, found 15 AI hackathons!
```

### Preferences  
```
User: "I'm interested in blockchain and fintech hackathons"
Nudge: ✅ Saved your preferences. I'll notify you about relevant hackathons.
```

### Proactive Notifications
```
Nudge: 🚨 New hackathon matches your interests:
• "DeFi Innovation Challenge" - $50K prize - Deadline: Nov 30
• "Blockchain for Good" - $25K prize - Deadline: Dec 15
```

## 🔒 Security & Safety

### AI Safety
- **Bedrock Guardrails**: Prevents malicious URL processing
- **Sandboxed Execution**: Generated code runs in isolated containers
- **Input Validation**: Strict filtering of user inputs and URLs

### Infrastructure Security  
- **IAM Least Privilege**: Role-based access with minimal permissions
- **VPC Isolation**: ECS tasks run in private subnets
- **Secrets Management**: Environment variables for sensitive data

## 💰 Cost & Scalability

### Serverless Architecture Benefits
- **Pay-per-use**: Lambda and Fargate scale to zero
- **Auto-scaling**: Handles 1 user to millions seamlessly  
- **Managed Services**: No infrastructure maintenance overhead

### Estimated Monthly Costs (1000 users)
- Bedrock API calls: ~$50
- ECS Fargate: ~$30  
- Lambda executions: ~$10
- DynamoDB: ~$20
- **Total: ~$110/month**

## 🎪 Demo Flow

1. **User Discovery**: "Find hackathons on a new site: example-hackathons.com"
2. **Real-time Analysis**: Scout analyzes site structure, finds no API
3. **Tool Generation**: Creates custom BeautifulSoup scraper in 30 seconds
4. **Data Extraction**: Executes scraper, finds 8 hackathons
5. **Smart Storage**: Saves data and reusable scraper function
6. **Proactive Nudging**: Nudge agent matches user interests, sends notifications

## 🏆 Competitive Advantages

1. **Autonomous Adaptation**: No manual scraper maintenance
2. **Multi-Agent Intelligence**: Specialized brains for different tasks  
3. **Proactive Engagement**: Users don't need to remember to check
4. **Scalable Architecture**: Enterprise-ready AWS infrastructure
5. **Cost Efficiency**: Serverless design optimizes resource usage

## 📈 Future Roadmap

- **Calendar Integration**: Auto-add hackathon deadlines
- **Team Formation**: Match users with complementary skills
- **Submission Tracking**: Monitor application status across platforms
- **Prize Analytics**: Historical prize data and trend analysis
- **Mobile App**: Native iOS/Android applications

---

**Built with ❤️ for the AWS AI Hackathon**  
*Demonstrating the future of intelligent automation*