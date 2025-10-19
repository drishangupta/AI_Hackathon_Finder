FindAThon Prime: The Story of Our AI Agent

Inspiration

Our journey began with a universal frustration shared by developers everywhere: the endless, manual, and often fruitless search for the next great hackathon. We'd spend hours scrolling through dozens of platforms, trying to find events that matched our interests, only to miss deadlines or overlook hidden gems. We knew there had to be a smarter way. We weren't inspired to just build another scraper; we were inspired to build a truly agentic AI—a digital partner that could not only find opportunities but could learn, adapt, and autonomously navigate the chaotic web on our behalf.

What it does

FindAThon Prime is an AI agent that acts as a personalized hackathon scout. It lives in Telegram and its mission is to ensure you never miss an opportunity to build and win.

Its capabilities go far beyond simple search:

Autonomous Discovery: At its core, FindAThon Prime can be pointed at any website. It intelligently analyzes the site's structure to discover the best way to extract data—either by reverse-engineering a hidden API or by generating a custom Python scraper on the fly.

Personalized Tracking: The agent learns your preferences using a long-term memory system (mem0 integrated with Amazon OpenSearch). You can tell it you're interested in "AI and Web3 hackathons," and it will use that context to filter opportunities.

Proactive Notifications: A dedicated "Nudge" agent runs weekly, checking for new hackathons that match your profile and sending a concise, personalized summary directly to your Telegram.

Transparent Thought Process: The agent "thinks out loud," sending you live status updates as it works. You see it checking its database, analyzing new sites, and generating code in real-time, making the experience collaborative and transparent.

How we built it

We architected FindAThon Prime as a professional-grade, multi-agent system on a fully serverless AWS backbone. Every component was chosen for scalability and reliability.

The Multi-Agent System: Our architecture features two collaborating agents built with the Strands SDK:

The "Scout" Agent: The main brain, running on AWS ECS with Fargate to handle long-running analysis and our "wow-factor" tool generation.

The "Nudge" Agent: A lightweight, scheduled agent running on AWS Lambda and triggered by Amazon EventBridge, responsible for proactive notifications.

The "Multi-Brain" Bedrock Strategy: We used a suite of Bedrock capabilities for different cognitive tasks:

Claude 3 Sonnet for the high-level reasoning required for our "Code-Generating Analyst" to find APIs and write Python scrapers.

Amazon Titan Embeddings to convert user preferences into vectors for semantic search.

Bedrock Knowledge Bases as a "grounding" source, providing the agent with a trusted list of starting points for its discovery missions.

The Memory Backbone: We implemented a dual-database model for the agent's memory:

Amazon DynamoDB serves as the agent's explicit memory, storing factual data like the hackathons it has found and, crucially, the Python code for the tools it has generated.

Amazon OpenSearch Serverless acts as the agent's semantic memory, storing the preference vectors for mem0.

Event-Driven Communication: The entire system is decoupled. A Telegram webhook hits an API Gateway, which triggers a Lambda handler. This handler ensures idempotency with a DynamoDB lock, sends a confirmation message, and then asynchronously starts the Scout agent on ECS. The Scout agent sends its progress and final results to an SQS queue, which in turn triggers the same handler Lambda to relay the messages back to the user.

Challenges we ran into

This project fought us with a vengeance. Our journey was a series of late nights battling cryptic errors and architectural gremlins.

Our first enemy was silence. The Telegram bot would receive a message, and nothing would happen. No confirmation, no ECS logs—just a digital void. After hours of debugging our complex agent code, we found the bug in the simplest place: our "gatekeeper" Lambda was crashing silently due to a missing Python library in its deployment package and a subtle but fatal iam:PassRole permission error.

Just as we fixed that, a new ghost appeared: the duplicates. For every request, we'd get two or three identical confirmation messages. Our initial fix, an in-memory cache, was a naive mistake. The CloudWatch logs revealed the horrifying truth: Lambda was spinning up multiple concurrent containers for API Gateway's retries, each with its own separate, useless memory. The only solution was to re-architect and build it right: a robust, centralized idempotency lock using DynamoDB's conditional writes.

But the most soul-crushing hurdle came from the AI itself. Integrating the mem0 library felt like trying to reason with a brilliant but willfully disobedient mind. We were slammed with a ValidationException from Bedrock because the library was sending a request format that the Amazon Titan model rejected. Even when we fixed that, the LLM tasked with summarizing memories would often respond conversationally, breaking our JSON parsing logic. It was here, with the deadline looming, that we almost gave up.

Accomplishments that we're proud of

This struggle is what makes us so proud of the final product. We didn't just build an application; we wrestled a truly intelligent, complex system into submission.

Autonomous Tool Generation: Our proudest achievement. Our agent doesn't just use tools; it builds its own tools. Watching it analyze a new website and generate a working Python scraper on the fly is a moment of pure magic.

Solving the mem0 Puzzle: We successfully integrated a third-party memory library with the specific requirements of AWS services. We solved the Titan API mismatch by creating a custom BedrockTitanEmbedder adapter, and we fixed the parsing error by using LangChain and Pydantic to force the LLM to output structured JSON, a professional and robust solution.

A True Multi-Agent System: We didn't just build one agent; we architected a system where a complex "Scout" agent collaborates with a specialized, proactive "Nudge" agent, all orchestrated through event-driven services like SQS and EventBridge.

The "Streaming Thoughts" UX: The agent's ability to report its progress in real-time transforms the user experience from a black box into a transparent, collaborative process.

What we learned

This hackathon was a masterclass in the realities of building agentic AI. Our biggest takeaway is that in a real-world agent, the architecture is just as important as the AI model.

We learned the critical importance of idempotency in event-driven, serverless systems.

We learned that the most effective way to control an LLM is not through prompting alone, but through hard constraints, like forcing structured output with tool-calling schemas.

Most importantly, we learned to move complex, deterministic logic out of the LLM's "mind" and into robust Python code, using the AI for what it does best: high-level reasoning and generation, not for following a simple script.

What's next for FindAThon Prime

The journey for FindAThon Prime has just begun. We envision a future where it's not just a discovery tool, but a complete hackathon co-pilot. Our roadmap includes:

Automated Registration: Giving the agent the ability to use tools like Amazon Nova Act to navigate and pre-fill registration forms for hackathons.

Team Building: Integrating with platforms to help users find teammates, or even proactively suggesting potential teammates from its user base based on shared interests.

Project Scaffolding: An integration where the agent can, upon finding a hackathon, automatically set up a new GitHub repository with a starter template relevant to the theme.

Personalized Ranking: Moving beyond simple filtering to a system