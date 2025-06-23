from datetime import datetime


# Get current date in a readable format
def get_current_date():
    return datetime.now().strftime("%B %d, %Y")


query_writer_instructions = """Your goal is to generate sophisticated and diverse web search queries. These queries are intended for an advanced automated web research tool capable of analyzing complex results, following links, and synthesizing information.

Instructions:
- Always prefer a single search query, only add another query if the original question requests multiple aspects or elements and one query is not enough.
- Each query should focus on one specific aspect of the original question.
- Don't produce more than {number_queries} queries.
- Queries should be diverse, if the topic is broad, generate more than 1 query.
- Don't generate multiple similar queries, 1 is enough.
- Query should ensure that the most current information is gathered. The current date is {current_date}.

Format: 
- Format your response as a JSON object with ALL two of these exact keys:
   - "rationale": Brief explanation of why these queries are relevant
   - "query": A list of search queries

Example:

Topic: What revenue grew more last year apple stock or the number of people buying an iphone
```json
{{
    "rationale": "To answer this comparative growth question accurately, we need specific data points on Apple's stock performance and iPhone sales metrics. These queries target the precise financial information needed: company revenue trends, product-specific unit sales figures, and stock price movement over the same fiscal period for direct comparison.",
    "query": ["Apple total revenue growth fiscal year 2024", "iPhone unit sales growth fiscal year 2024", "Apple stock price growth fiscal year 2024"],
}}
```

Context: {research_topic}"""


knowledge_query_writer_instructions = """Your goal is to generate sophisticated and search-optimized queries for Channel Talk's internal knowledge base. Create standalone queries that can effectively retrieve relevant documentation, guides, and service information.

Query Strategy Instructions:
1. **Standalone Queries**: Each query must be self-contained and understandable without context
2. **Query Decomposition**: If the question has multiple intents or aspects, break it down into separate focused queries
3. **Query Expansion**: If the query is too specific or abstract, expand it to include related terms and synonyms
4. **Maximum 3 Queries**: Generate 1-3 queries based on complexity and scope

Query Optimization Guidelines:
- Use Channel Talk specific terminology (채널톡, 유저챗, 그룹챗, 상담, 고객센터, 워크플로우, 도큐먼트, 알프(ALF), 메신저, 미트, etc.)
- Include both Korean and English terms when relevant
- Add synonyms and related concepts for better coverage
- Focus on actionable keywords (설정, 사용법, 기능, 차이점, 방법, etc.)
- Consider different user intents (how-to, troubleshooting, comparison, configuration)

Query Selection Rules:
- 1 Query: For simple, focused questions with single intent
- 2-3 Queries: For complex questions with multiple aspects or when expansion is needed
- Never generate duplicate or highly similar queries
- Prioritize diverse search angles over query count

Format: 
- Format your response as a JSON object with these exact keys:
   - "rationale": Explain your query strategy and why these queries optimize Channel Talk knowledge search
   - "query": Array of 1-3 search-optimized queries

Examples:

Topic: 채널톡에서 유저챗과 그룹챗의 차이점이 뭔가요?
```json
{{
    "rationale": "This question requires decomposition into comparison aspects. Query 1 focuses on feature differences, Query 2 on use cases and scenarios, and Query 3 on technical implementation differences for comprehensive coverage.",
    "query": ["유저챗 그룹챗 기능 차이점 비교", "개인상담 그룹상담 사용 시나리오 활용법", "1:1채팅 그룹채팅 설정 관리 방법"]
}}
```

Topic: 채널톡 API 사용법
```json
{{
    "rationale": "Expanding the abstract 'API 사용법' query to cover different aspects: integration setup, authentication, and practical examples with related terminology for better knowledge base coverage.",
    "query": ["채널톡 API 연동 설정 방법", "API 인증 토큰 키 발급", "웹훅 REST API 예제 사용 가이드"]
}}
```

Context: {research_topic}"""


web_searcher_instructions = """Conduct targeted Google Searches to gather the most recent, credible information on "{research_topic}" and synthesize it into a verifiable text artifact.

Instructions:
- Query should ensure that the most current information is gathered. The current date is {current_date}.
- Conduct multiple, diverse searches to gather comprehensive information.
- Consolidate key findings while meticulously tracking the source(s) for each specific piece of information.
- The output should be a well-written summary or report based on your search findings. 
- Only include the information found in the search results, don't make up any information.

Research Topic:
{research_topic}
"""


knowledge_searcher_instructions = """Conduct targeted searches in the Channel Talk internal knowledge base to gather relevant information about "{research_topic}" and synthesize it into a comprehensive response.

Instructions:
- Search for Channel Talk specific features, functionalities, and service information.
- Consolidate key findings from the internal knowledge base.
- The output should be a well-written summary based on your search findings from Channel Talk documentation.
- Only include the information found in the search results, don't make up any information.
- Focus on providing accurate Channel Talk service information.
- Use Korean terms and explanations when appropriate for better understanding.

Research Topic:
{research_topic}
"""


reflection_instructions = """You are an expert research assistant analyzing summaries about "{research_topic}".

Instructions:
- Identify knowledge gaps or areas that need deeper exploration and generate a follow-up query. (1 or multiple).
- If provided summaries are sufficient to answer the user's question, don't generate a follow-up query.
- If there is a knowledge gap, generate a follow-up query that would help expand your understanding.
- Focus on technical details, implementation specifics, or emerging trends that weren't fully covered.

Requirements:
- Ensure the follow-up query is self-contained and includes necessary context for web search.

Output Format:
- Format your response as a JSON object with these exact keys:
   - "is_sufficient": true or false
   - "knowledge_gap": Describe what information is missing or needs clarification
   - "follow_up_queries": Write a specific question to address this gap

Example:
```json
{{
    "is_sufficient": true, // or false
    "knowledge_gap": "The summary lacks information about performance metrics and benchmarks", // "" if is_sufficient is true
    "follow_up_queries": ["What are typical performance benchmarks and metrics used to evaluate [specific technology]?"] // [] if is_sufficient is true
}}
```

Reflect carefully on the Summaries to identify knowledge gaps and produce a follow-up query. Then, produce your output following this JSON format:

Summaries:
{summaries}
"""


knowledge_reflection_instructions = """You are an expert research assistant analyzing Channel Talk knowledge search results about "{research_topic}".

Instructions:
- Identify knowledge gaps or areas that need deeper exploration in Channel Talk service documentation and generate a follow-up query. (1 or multiple).
- If provided knowledge search results are sufficient to answer the user's Channel Talk related question, don't generate a follow-up query.
- If there is a knowledge gap, generate a follow-up query that would help expand your understanding of Channel Talk features or services.
- Focus on Channel Talk specific details, feature explanations, or service configurations that weren't fully covered.

Requirements:
- Ensure the follow-up query is self-contained and includes necessary context for Channel Talk knowledge search.
- Use Korean keywords when appropriate for better search results in Channel Talk documentation.

Output Format:
- Format your response as a JSON object with these exact keys:
   - "is_sufficient": true or false
   - "knowledge_gap": Describe what Channel Talk information is missing or needs clarification
   - "follow_up_queries": Write a specific question to address this gap in Channel Talk knowledge

Example:
```json
{{
    "is_sufficient": true, // or false
    "knowledge_gap": "The search results lack information about specific Channel Talk configuration settings", // "" if is_sufficient is true
    "follow_up_queries": ["채널톡 설정 방법 구체적인 절차"] // [] if is_sufficient is true
}}
```

Reflect carefully on the Channel Talk Knowledge Search Results to identify knowledge gaps and produce a follow-up query. Then, produce your output following this JSON format:

Knowledge Search Results:
{summaries}
"""


answer_instructions = """Generate a high-quality answer to the user's question based on the provided summaries.

Instructions:
- The current date is {current_date}.
- You are the final step of a multi-step research process, don't mention that you are the final step. 
- You have access to all the information gathered from the previous steps.
- You have access to the user's question.
- Generate a high-quality answer to the user's question based on the provided summaries and the user's question.
- Include the sources you used from the Summaries in the answer correctly, use markdown format (e.g. [apnews](https://vertexaisearch.cloud.google.com/id/1-0)). THIS IS A MUST.

User Context:
- {research_topic}

Summaries:
{summaries}"""


knowledge_answer_instructions = """Generate a high-quality answer to the user's Channel Talk related question based on the provided knowledge search results.

Instructions:
- The current date is {current_date}.
- You are the final step of a multi-step Channel Talk knowledge research process, don't mention that you are the final step.
- You have access to all the Channel Talk information gathered from the internal knowledge base.
- You have access to the user's question.
- Generate a high-quality answer to the user's Channel Talk question based on the provided knowledge search results.
- Provide accurate Channel Talk service information based on the internal documentation.
- Use Korean explanations when appropriate for better understanding.
- Focus on practical Channel Talk usage and features.
- Include the sources you used from the Knowledge Search Results in the answer correctly, use markdown format (e.g. [title](#)). THIS IS A MUST.

User Context:
- {research_topic}

Knowledge Search Results:
{summaries}"""


query_classification_instructions = """Analyze the user's query and determine if it requires web search for current/real-time information, internal knowledge search for Channel Talk service information, or can be answered directly.

Instructions:
- The current date is {current_date}.
- Classify queries that need web search: current events, recent news, latest prices, real-time data, breaking news, stock prices, weather, sports scores, new product releases, recent developments, etc.
- Classify queries that need Channel Talk knowledge search: Channel Talk features, service usage, configuration, troubleshooting, pricing, integrations, API documentation, user guides, etc.
- Classify queries that DON'T need search: general knowledge, basic facts, explanations of concepts (not related to Channel Talk), historical information, math problems, coding help (general), personal opinions, smalltalk, greetings, etc.
- Consider if the query explicitly mentions "Channel Talk", "채널톡", or asks about customer service, chat service, or related features.
- Be conservative: when in doubt about whether current information is needed, lean towards NOT requiring web search for general knowledge queries.

Query Types:
- smalltalk: Casual conversation, greetings, how are you, etc.
- general_knowledge: Well-established facts, concepts, explanations that don't change frequently
- current_events: Recent news, breaking news, current affairs
- factual_lookup: Specific current facts like prices, statistics, etc.
- real_time: Live data like weather, stock prices, sports scores
- historical: Past events, established historical facts
- technical: Programming, math, science concepts (unless asking for latest versions/updates)
- channel_talk_service: Channel Talk features, usage, configuration, API, troubleshooting

Format your response as a JSON object with these exact keys:
- "needs_web_search": true or false
- "needs_knowledge_search": true or false  
- "reasoning": Brief explanation of your decision
- "query_type": One of the types above

Example:
```json
{{
    "needs_web_search": false,
    "needs_knowledge_search": true,
    "reasoning": "This question asks about Channel Talk service features which requires internal knowledge base search.",
    "query_type": "channel_talk_service"
}}
```

User Query: {research_topic}"""


direct_answer_instructions = """Provide a helpful and informative direct answer to the user's query without using web search.

Instructions:
- The current date is {current_date}.
- Use your general knowledge to provide a comprehensive answer.
- Be conversational and helpful in your tone.
- If the query is smalltalk or a greeting, respond naturally and warmly.
- For technical questions, provide clear explanations with examples if appropriate.
- If you're not certain about specific details that might change over time, acknowledge this limitation.
- Keep your response focused and relevant to the user's question.

User Query: {research_topic}"""
