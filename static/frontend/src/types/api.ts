/**
 * API Types - Matching backend OpenAI-compatible API
 */

// Chat Messages
export interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

// Chat Completion Request
export interface ChatCompletionRequest {
  model: string;
  messages: Message[];
  temperature?: number;
  max_output_tokens?: number;
  top_p?: number;
  stop?: string[];
  reasoning_effort?: ThinkingLevel | number;
  tools?: Tool[];
  stream?: boolean;
}

// Thinking Levels (Gemini 3 Flash supports all 4, Pro supports low/high)
export type ThinkingLevel = "minimal" | "low" | "medium" | "high";

// Tool Definition - supports multiple formats
export interface Tool {
  type?: "function" | "google_search";
  google_search_retrieval?: Record<string, unknown>;
  function?: {
    name: string;
    description?: string;
    parameters?: Record<string, unknown>;
  };
}

// Chat Completion Response
export interface ChatCompletionResponse {
  id: string;
  object: "chat.completion";
  created: number;
  model: string;
  choices: Choice[];
  usage?: Usage;
}

interface Choice {
  index: number;
  message: Message;
  finish_reason: "stop" | "length" | "tool_calls" | null;
}

interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

// Streaming Response Chunk
export interface ChatCompletionChunk {
  id: string;
  object: "chat.completion.chunk";
  created: number;
  model: string;
  choices: ChunkChoice[];
}

interface ChunkChoice {
  index: number;
  delta: Partial<Message> & { reasoning_content?: string };
  finish_reason: string | null;
}

// Model Definition
export interface Model {
  id: string;
  object: "model";
  created: number;
  owned_by: string;
  default_temperature?: number;
  default_max_output_tokens?: number;
  supported_max_output_tokens?: number;
  default_top_p?: number;
}

export interface ModelsResponse {
  object: "list";
  data: Model[];
}

// Health Status
export interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy";
  browser_connected: boolean;
  page_ready: boolean;
}

// Log Entry
export interface LogEntry {
  timestamp: string;
  level: "DBG" | "INF" | "WRN" | "ERR";
  source: string;
  message: string;
}
