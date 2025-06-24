import { useStream } from "@langchain/langgraph-sdk/react";
import type { Message } from "@langchain/langgraph-sdk";
import { useState, useEffect, useRef, useCallback } from "react";
import { ProcessedEvent } from "@/components/ActivityTimeline";
import { WelcomeScreen } from "@/components/WelcomeScreen";
import { ChatMessagesView } from "@/components/ChatMessagesView";
import { Button } from "@/components/ui/button";

export default function App() {
  const [processedEventsTimeline, setProcessedEventsTimeline] = useState<
    ProcessedEvent[]
  >([]);
  const [historicalActivities, setHistoricalActivities] = useState<
    Record<string, ProcessedEvent[]>
  >({});
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const hasFinalizeEventOccurredRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const thread = useStream<{
    messages: Message[];
    initial_search_query_count: number;
    max_research_loops: number;
    reasoning_model: string;
  }>({
    apiUrl: import.meta.env.DEV
      ? "http://localhost:2024"
      : "http://localhost:8123",
    assistantId: "agent",
    messagesKey: "messages",
    onUpdateEvent: (event: any) => {
      let processedEvent: ProcessedEvent | null = null;
      if (event.input_guardrail) {
        const isSafe = event.input_guardrail?.is_safe_input;
        const violations = event.input_guardrail?.guardrail_violations || [];
        const originalInput = event.input_guardrail?.original_input || "";
        
        if (isSafe) {
          processedEvent = {
            title: "🛡️ Input Security Check",
            data: `Input validated successfully. Safe to proceed with: "${originalInput.substring(0, 50)}${originalInput.length > 50 ? '...' : ''}"`
          };
        } else {
          processedEvent = {
            title: "🚨 Security Violation Detected",
            data: `Input blocked due to: ${violations.join(", ")}. Original input length: ${originalInput.length} characters.`
          };
        }
      } else if (event.guardrail_block) {
        processedEvent = {
          title: "🛡️ Request Blocked",
          data: "Request has been blocked by security guardrails for policy violations."
        };
      } else if (event.generate_query) {
        processedEvent = {
          title: "Generating Search Queries",
          data: event.generate_query?.search_query?.join(", ") || "",
        };
      } else if (event.generate_knowledge_query) {
        processedEvent = {
          title: "Generating Knowledge Search Queries",
          data: event.generate_knowledge_query?.search_query?.join(", ") || "",
        };
      } else if (event.web_research) {
        const sources = event.web_research.sources_gathered || [];
        const numSources = sources.length;
        const uniqueLabels = [
          ...new Set(sources.map((s: any) => s.label).filter(Boolean)),
        ];
        const exampleLabels = uniqueLabels.slice(0, 3).join(", ");
        processedEvent = {
          title: "Web Research",
          data: `Gathered ${numSources} sources. Related to: ${
            exampleLabels || "N/A"
          }.`,
        };
      } else if (event.classify_query) {
        const needsWebSearch = event.classify_query?.needs_web_search || false;
        const needsKnowledgeSearch = event.classify_query?.needs_knowledge_search || false;
        
        let searchTypeText = "";
        if (needsWebSearch && needsKnowledgeSearch) {
          searchTypeText = "🌐📚 Web + Knowledge Search";
        } else if (needsWebSearch) {
          searchTypeText = "🌐 Web Search";
        } else if (needsKnowledgeSearch) {
          searchTypeText = "📚 Knowledge Search";
        } else {
          searchTypeText = "💬 Direct Answer";
        }
        
        processedEvent = {
          title: "🔍 Query Classification",
          data: `Target Node: ${searchTypeText}`,
        };
      } else if (event.knowledge_search) {
        const results = event.knowledge_search.knowledge_search_result || [];
        const searchQuery = event.knowledge_search.search_query?.[0] || "";
        const numResults = results.length;
        processedEvent = {
          title: "Knowledge Search",
          data: `Searching: "${searchQuery}". Found ${numResults} relevant result${numResults !== 1 ? 's' : ''} in internal knowledge base.`,
        };
      } else if (event.reflection) {
        const isSufficient = event.reflection.is_sufficient || false;
        const knowledgeGap = event.reflection.knowledge_gap || "No gap identified";
        const followUpQueries = event.reflection.follow_up_queries || [];
        
        // Array를 문자열로 변환
        const queriesText = Array.isArray(followUpQueries) 
        processedEvent = {
          title: "Reflection",
          data: `Analysing Web Research Results: \n${isSufficient ? "✅ Sufficient" : "❌ Insufficient"}. \nReason: ${knowledgeGap}. \nFollow-up Queries: ${queriesText}`,
        };
      } else if (event.knowledge_reflection) {
        const isSufficient = event.knowledge_reflection.is_sufficient || false;
        const knowledgeGap = event.knowledge_reflection.knowledge_gap || "No gap identified";
        const followUpQueries = event.knowledge_reflection.follow_up_queries || [];
        
        // Array를 문자열로 변환
        const queriesText = Array.isArray(followUpQueries) 
          ? followUpQueries.join(", ") 
          : followUpQueries?.toString() || "No follow-up queries";
          
        processedEvent = {
          title: "Knowledge Reflection",
          data: `Analysing Knowledge Search Results: \n${isSufficient ? "✅ Sufficient" : "❌ Insufficient"}. \nReason: ${knowledgeGap}. \nFollow-up Queries: ${queriesText}`,
        };
      } else if (event.finalize_answer) {
        processedEvent = {
          title: "Finalizing Answer",
          data: "Composing and presenting the final answer.",
        };
        hasFinalizeEventOccurredRef.current = true;
      } else if (event.finalize_knowledge_answer) {
        processedEvent = {
          title: "Finalizing Knowledge Answer",
          data: "Composing and presenting the final knowledge-based answer.",
        };
        hasFinalizeEventOccurredRef.current = true;
      }
      if (processedEvent) {
        setProcessedEventsTimeline((prevEvents) => [
          ...prevEvents,
          processedEvent!,
        ]);
      }
    },
    onError: (error: any) => {
      setError(error.message);
    },
  });

  useEffect(() => {
    if (scrollAreaRef.current) {
      const scrollViewport = scrollAreaRef.current.querySelector(
        "[data-radix-scroll-area-viewport]"
      );
      if (scrollViewport) {
        scrollViewport.scrollTop = scrollViewport.scrollHeight;
      }
    }
  }, [thread.messages]);

  useEffect(() => {
    if (
      hasFinalizeEventOccurredRef.current &&
      !thread.isLoading &&
      thread.messages.length > 0
    ) {
      const lastMessage = thread.messages[thread.messages.length - 1];
      if (lastMessage && lastMessage.type === "ai" && lastMessage.id) {
        setHistoricalActivities((prev) => ({
          ...prev,
          [lastMessage.id!]: [...processedEventsTimeline],
        }));
      }
      hasFinalizeEventOccurredRef.current = false;
    }
  }, [thread.messages, thread.isLoading, processedEventsTimeline]);

  const handleSubmit = useCallback(
    (submittedInputValue: string, effort: string, model: string) => {
      if (!submittedInputValue.trim()) return;
      setProcessedEventsTimeline([]);
      hasFinalizeEventOccurredRef.current = false;

      // convert effort to, initial_search_query_count and max_research_loops
      // low means max 1 loop and 1 query
      // medium means max 3 loops and 3 queries
      // high means max 10 loops and 5 queries
      let initial_search_query_count = 0;
      let max_research_loops = 0;
      switch (effort) {
        case "low":
          initial_search_query_count = 1;
          max_research_loops = 1;
          break;
        case "medium":
          initial_search_query_count = 3;
          max_research_loops = 3;
          break;
        case "high":
          initial_search_query_count = 5;
          max_research_loops = 10;
          break;
      }

      const newMessages: Message[] = [
        ...(thread.messages || []),
        {
          type: "human",
          content: submittedInputValue,
          id: Date.now().toString(),
        },
      ];
      thread.submit({
        messages: newMessages,
        initial_search_query_count: initial_search_query_count,
        max_research_loops: max_research_loops,
        reasoning_model: model,
      });
    },
    [thread]
  );

  const handleCancel = useCallback(() => {
    thread.stop();
    window.location.reload();
  }, [thread]);

  return (
    <div className="flex h-screen bg-neutral-800 text-neutral-100 font-sans antialiased">
      <main className="h-full w-full max-w-4xl mx-auto">
          {thread.messages.length === 0 ? (
            <WelcomeScreen
              handleSubmit={handleSubmit}
              isLoading={thread.isLoading}
              onCancel={handleCancel}
            />
          ) : error ? (
            <div className="flex flex-col items-center justify-center h-full">
              <div className="flex flex-col items-center justify-center gap-4">
                <h1 className="text-2xl text-red-400 font-bold">Error</h1>
                <p className="text-red-400">{JSON.stringify(error)}</p>

                <Button
                  variant="destructive"
                  onClick={() => window.location.reload()}
                >
                  Retry
                </Button>
              </div>
            </div>
          ) : (
            <ChatMessagesView
              messages={thread.messages}
              isLoading={thread.isLoading}
              scrollAreaRef={scrollAreaRef}
              onSubmit={handleSubmit}
              onCancel={handleCancel}
              liveActivityEvents={processedEventsTimeline}
              historicalActivities={historicalActivities}
            />
          )}
      </main>
    </div>
  );
}
