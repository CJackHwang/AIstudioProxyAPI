/**
 * API Client - Centralized HTTP client with error handling
 */

import type {
  ChatCompletionRequest,
  ChatCompletionResponse,
  ChatCompletionChunk,
  ModelsResponse,
  HealthStatus,
} from "@/types";

// Custom API Error
export class ApiError extends Error {
  status: number;
  userMessage: string;
  details?: unknown;

  constructor(status: number, userMessage: string, details?: unknown) {
    super(userMessage);
    this.name = "ApiError";
    this.status = status;
    this.userMessage = userMessage;
    this.details = details;
  }
}

// Base fetch wrapper with error handling
async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  try {
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
      ...options,
    });

    if (!response.ok) {
      const errorBody = await response.text();
      throw new ApiError(
        response.status,
        `请求失败: ${response.statusText}`,
        errorBody
      );
    }

    return response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, "网络错误，请检查连接", error);
  }
}

// Models API
export async function fetchModels(): Promise<ModelsResponse> {
  return fetchApi<ModelsResponse>("/v1/models");
}

// Health API
export async function fetchHealth(): Promise<HealthStatus> {
  return fetchApi<HealthStatus>("/health");
}

// Chat API (non-streaming)
export async function sendChatCompletion(
  request: ChatCompletionRequest
): Promise<ChatCompletionResponse> {
  return fetchApi<ChatCompletionResponse>("/v1/chat/completions", {
    method: "POST",
    body: JSON.stringify({ ...request, stream: false }),
  });
}

// Chat API (streaming) - Returns async generator
export async function* streamChatCompletion(
  request: ChatCompletionRequest,
  signal?: AbortSignal
): AsyncGenerator<ChatCompletionChunk, void, unknown> {
  const response = await fetch("/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...request, stream: true }),
    signal,
  });

  if (!response.ok) {
    throw new ApiError(response.status, `请求失败: ${response.statusText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new ApiError(0, "无法读取响应流");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed === "data: [DONE]") continue;
        if (!trimmed.startsWith("data: ")) continue;

        try {
          const json = JSON.parse(trimmed.slice(6));
          yield json as ChatCompletionChunk;
        } catch {
          // Skip malformed JSON
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// ============================================
// Proxy Configuration API
// ============================================

export interface ProxyConfig {
  enabled: boolean;
  address: string;
}

export interface ProxyTestResult {
  success: boolean;
  message: string;
  latency_ms?: number;
}

export async function fetchProxyConfig(): Promise<ProxyConfig> {
  return fetchApi<ProxyConfig>("/api/proxy/config");
}

export async function updateProxyConfig(
  config: ProxyConfig
): Promise<{ success: boolean; config: ProxyConfig }> {
  return fetchApi("/api/proxy/config", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function testProxyConnectivity(
  address: string,
  testUrl?: string
): Promise<ProxyTestResult> {
  return fetchApi<ProxyTestResult>("/api/proxy/test", {
    method: "POST",
    body: JSON.stringify({
      address,
      test_url: testUrl || "http://httpbin.org/get",
    }),
  });
}

// ============================================
// Auth Files API
// ============================================

interface AuthFileInfo {
  name: string;
  path: string;
  size_bytes: number;
  is_active: boolean;
}

interface AuthFilesResponse {
  saved_files: AuthFileInfo[];
  active_file: string | null;
}

export async function fetchAuthFiles(): Promise<AuthFilesResponse> {
  return fetchApi<AuthFilesResponse>("/api/auth/files");
}

export async function fetchActiveAuth(): Promise<{
  active_file: string | null;
}> {
  return fetchApi("/api/auth/active");
}

export async function activateAuthFile(
  filename: string
): Promise<{ success: boolean; message: string; active_file: string }> {
  return fetchApi("/api/auth/activate", {
    method: "POST",
    body: JSON.stringify({ filename }),
  });
}

export async function deactivateAuth(): Promise<{
  success: boolean;
  message: string;
}> {
  return fetchApi("/api/auth/deactivate", {
    method: "DELETE",
  });
}

// ============================================
// Ports Configuration API
// ============================================

export interface PortConfig {
  fastapi_port: number;
  camoufox_debug_port: number;
  stream_proxy_port: number;
  stream_proxy_enabled: boolean;
}

interface ProcessInfo {
  pid: number;
  name: string;
}

interface PortStatusInfo {
  port: number;
  port_type: string;
  in_use: boolean;
  processes: ProcessInfo[];
}

export async function fetchPortConfig(): Promise<PortConfig> {
  return fetchApi<PortConfig>("/api/ports/config");
}

export async function updatePortConfig(
  config: PortConfig
): Promise<{ success: boolean; message: string; config: PortConfig }> {
  return fetchApi("/api/ports/config", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function fetchPortStatus(): Promise<{ ports: PortStatusInfo[] }> {
  return fetchApi("/api/ports/status");
}

export async function killProcess(
  pid: number
): Promise<{ success: boolean; message: string; pid: number }> {
  return fetchApi("/api/ports/kill", {
    method: "POST",
    body: JSON.stringify({ pid, confirm: true }),
  });
}
