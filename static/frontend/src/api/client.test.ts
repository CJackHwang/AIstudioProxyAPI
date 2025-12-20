/**
 * API Client Tests
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ApiError } from "./client";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("ApiError", () => {
  it("creates error with status and message", () => {
    const error = new ApiError(404, "Not Found");

    expect(error.status).toBe(404);
    expect(error.userMessage).toBe("Not Found");
    expect(error.message).toBe("Not Found");
    expect(error.name).toBe("ApiError");
  });

  it("stores optional details", () => {
    const details = { code: "ERR_001", context: "test" };
    const error = new ApiError(500, "Server Error", details);

    expect(error.details).toEqual(details);
  });

  it("is instanceof Error", () => {
    const error = new ApiError(400, "Bad Request");

    expect(error instanceof Error).toBe(true);
    expect(error instanceof ApiError).toBe(true);
  });
});

describe("fetchApi (via exported functions)", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("fetchModels", () => {
    it("returns models on success", async () => {
      const mockResponse = {
        object: "list",
        data: [
          {
            id: "gemini-2.5-pro",
            object: "model",
            created: 1234567890,
            owned_by: "google",
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      // Dynamic import to get fresh module with mocked fetch
      const { fetchModels } = await import("./client");
      const result = await fetchModels();

      expect(result).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        "/v1/models",
        expect.objectContaining({
          headers: expect.objectContaining({
            "Content-Type": "application/json",
          }),
        })
      );
    });

    it("throws ApiError on non-ok response", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        text: async () => "Server overloaded",
      });

      const { fetchModels } = await import("./client");

      await expect(fetchModels()).rejects.toThrow(ApiError);
    });
  });

  describe("fetchHealth", () => {
    it("returns health status on success", async () => {
      const mockHealth = {
        status: "healthy",
        browser_connected: true,
        page_ready: true,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockHealth,
      });

      const { fetchHealth } = await import("./client");
      const result = await fetchHealth();

      expect(result).toEqual(mockHealth);
    });
  });

  describe("sendChatCompletion", () => {
    it("sends POST request with stream: false", async () => {
      const mockResponse = {
        id: "chatcmpl-123",
        object: "chat.completion",
        created: Date.now(),
        model: "gemini-2.5-pro",
        choices: [
          {
            index: 0,
            message: { role: "assistant", content: "Hello!" },
            finish_reason: "stop",
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { sendChatCompletion } = await import("./client");
      const result = await sendChatCompletion({
        model: "gemini-2.5-pro",
        messages: [{ role: "user", content: "Hi" }],
      });

      expect(result).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        "/v1/chat/completions",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"stream":false'),
        })
      );
    });
  });

  describe("Proxy Config API", () => {
    it("fetchProxyConfig returns config", async () => {
      const mockConfig = { enabled: true, address: "http://proxy:8080" };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockConfig,
      });

      const { fetchProxyConfig } = await import("./client");
      const result = await fetchProxyConfig();

      expect(result).toEqual(mockConfig);
    });

    it("updateProxyConfig sends POST", async () => {
      const mockResponse = {
        success: true,
        config: { enabled: true, address: "http://new-proxy:8080" },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { updateProxyConfig } = await import("./client");
      const result = await updateProxyConfig({
        enabled: true,
        address: "http://new-proxy:8080",
      });

      expect(result).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/proxy/config",
        expect.objectContaining({
          method: "POST",
        })
      );
    });

    it("testProxyConnectivity sends test request", async () => {
      const mockResult = {
        success: true,
        message: "Connected",
        latency_ms: 42,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResult,
      });

      const { testProxyConnectivity } = await import("./client");
      const result = await testProxyConnectivity(
        "http://proxy:8080",
        "http://example.com"
      );

      expect(result).toEqual(mockResult);
    });

    it("testProxyConnectivity uses default test URL when not provided", async () => {
      const mockResult = {
        success: true,
        message: "Connected",
        latency_ms: 50,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResult,
      });

      const { testProxyConnectivity } = await import("./client");
      const result = await testProxyConnectivity("http://proxy:8080");

      expect(result).toEqual(mockResult);
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/proxy/test",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("httpbin.org"),
        })
      );
    });
  });

  describe("Auth Files API", () => {
    it("fetchAuthFiles returns file list", async () => {
      const mockResponse = {
        saved_files: [
          {
            name: "auth1.json",
            path: "/data/auth1.json",
            size_bytes: 1234,
            is_active: true,
          },
        ],
        active_file: "auth1.json",
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { fetchAuthFiles } = await import("./client");
      const result = await fetchAuthFiles();

      expect(result).toEqual(mockResponse);
    });

    it("activateAuthFile sends activation request", async () => {
      const mockResponse = {
        success: true,
        message: "Activated",
        active_file: "auth2.json",
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { activateAuthFile } = await import("./client");
      const result = await activateAuthFile("auth2.json");

      expect(result).toEqual(mockResponse);
    });

    it("deactivateAuth sends DELETE request", async () => {
      const mockResponse = { success: true, message: "Deactivated" };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { deactivateAuth } = await import("./client");
      const result = await deactivateAuth();

      expect(result).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/auth/deactivate",
        expect.objectContaining({
          method: "DELETE",
        })
      );
    });
  });

  describe("Ports API", () => {
    it("fetchPortConfig returns port configuration", async () => {
      const mockConfig = {
        fastapi_port: 2048,
        camoufox_debug_port: 9222,
        stream_proxy_port: 8888,
        stream_proxy_enabled: true,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockConfig,
      });

      const { fetchPortConfig } = await import("./client");
      const result = await fetchPortConfig();

      expect(result).toEqual(mockConfig);
    });

    it("fetchPortStatus returns status info", async () => {
      const mockStatus = {
        ports: [
          {
            port: 2048,
            port_type: "fastapi",
            in_use: true,
            processes: [{ pid: 1234, name: "python" }],
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockStatus,
      });

      const { fetchPortStatus } = await import("./client");
      const result = await fetchPortStatus();

      expect(result).toEqual(mockStatus);
    });

    it("killProcess sends kill request with confirmation", async () => {
      const mockResponse = {
        success: true,
        message: "Process killed",
        pid: 1234,
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { killProcess } = await import("./client");
      const result = await killProcess(1234);

      expect(result).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/ports/kill",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"confirm":true'),
        })
      );
    });
  });

  describe("Network Error Handling", () => {
    it("throws ApiError with status 0 on network failure", async () => {
      mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

      const { fetchModels } = await import("./client");

      await expect(fetchModels()).rejects.toMatchObject({
        status: 0,
        userMessage: expect.stringContaining("网络错误"),
      });
    });
  });

  describe("streamChatCompletion", () => {
    // Helper to create a mock ReadableStream
    function createMockStream(chunks: string[]): ReadableStream<Uint8Array> {
      const encoder = new TextEncoder();
      let index = 0;

      return new ReadableStream({
        pull(controller) {
          if (index < chunks.length) {
            controller.enqueue(encoder.encode(chunks[index]));
            index++;
          } else {
            controller.close();
          }
        },
      });
    }

    it("yields chunks from SSE stream", async () => {
      const mockChunks = [
        'data: {"id":"1","choices":[{"delta":{"content":"Hello"}}]}\n',
        'data: {"id":"2","choices":[{"delta":{"content":" World"}}]}\n',
        "data: [DONE]\n",
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        body: createMockStream(mockChunks),
      });

      const { streamChatCompletion } = await import("./client");
      const results: unknown[] = [];

      for await (const chunk of streamChatCompletion({
        model: "gemini-2.5-pro",
        messages: [{ role: "user", content: "Hi" }],
      })) {
        results.push(chunk);
      }

      expect(results).toHaveLength(2);
      expect(results[0]).toEqual({
        id: "1",
        choices: [{ delta: { content: "Hello" } }],
      });
      expect(results[1]).toEqual({
        id: "2",
        choices: [{ delta: { content: " World" } }],
      });
    });

    it("throws ApiError on non-ok response", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
      });

      const { streamChatCompletion } = await import("./client");
      const generator = streamChatCompletion({
        model: "gemini-2.5-pro",
        messages: [{ role: "user", content: "Hi" }],
      });

      await expect(generator.next()).rejects.toThrow();
    });

    it("throws ApiError when response body is null", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        body: null,
      });

      const { streamChatCompletion } = await import("./client");
      const generator = streamChatCompletion({
        model: "gemini-2.5-pro",
        messages: [{ role: "user", content: "Hi" }],
      });

      await expect(generator.next()).rejects.toMatchObject({
        userMessage: expect.stringContaining("无法读取响应流"),
      });
    });

    it("skips malformed JSON without crashing", async () => {
      const mockChunks = [
        'data: {"id":"1","valid":true}\n',
        "data: {invalid json\n",
        'data: {"id":"2","valid":true}\n',
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        body: createMockStream(mockChunks),
      });

      const { streamChatCompletion } = await import("./client");
      const results: unknown[] = [];

      for await (const chunk of streamChatCompletion({
        model: "test",
        messages: [{ role: "user", content: "test" }],
      })) {
        results.push(chunk);
      }

      // Should have 2 valid chunks, malformed one was skipped
      expect(results).toHaveLength(2);
    });

    it("handles chunked data spanning multiple reads", async () => {
      // Simulate data split across chunk boundaries
      const mockChunks = [
        'data: {"id":"1","partial":',
        '"value"}\ndata: {"id":"2"}\n',
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        body: createMockStream(mockChunks),
      });

      const { streamChatCompletion } = await import("./client");
      const results: unknown[] = [];

      for await (const chunk of streamChatCompletion({
        model: "test",
        messages: [{ role: "user", content: "test" }],
      })) {
        results.push(chunk);
      }

      expect(results).toHaveLength(2);
      expect(results[0]).toEqual({ id: "1", partial: "value" });
      expect(results[1]).toEqual({ id: "2" });
    });

    it("ignores empty lines and non-data lines", async () => {
      const mockChunks = [
        "\n",
        ":comment line\n",
        "event: message\n",
        'data: {"id":"1"}\n',
        "\n",
      ];

      mockFetch.mockResolvedValueOnce({
        ok: true,
        body: createMockStream(mockChunks),
      });

      const { streamChatCompletion } = await import("./client");
      const results: unknown[] = [];

      for await (const chunk of streamChatCompletion({
        model: "test",
        messages: [{ role: "user", content: "test" }],
      })) {
        results.push(chunk);
      }

      expect(results).toHaveLength(1);
      expect(results[0]).toEqual({ id: "1" });
    });

    it("passes abort signal to fetch", async () => {
      const controller = new AbortController();

      mockFetch.mockResolvedValueOnce({
        ok: true,
        body: createMockStream(['data: {"id":"1"}\n']),
      });

      const { streamChatCompletion } = await import("./client");

      // Just verify it doesn't throw when signal is passed
      for await (const _ of streamChatCompletion(
        { model: "test", messages: [{ role: "user", content: "test" }] },
        controller.signal
      )) {
        // consume
      }

      expect(mockFetch).toHaveBeenCalledWith(
        "/v1/chat/completions",
        expect.objectContaining({ signal: controller.signal })
      );
    });
  });

  describe("fetchActiveAuth", () => {
    it("returns active auth file", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ active_file: "auth.json" }),
      });

      const { fetchActiveAuth } = await import("./client");
      const result = await fetchActiveAuth();

      expect(result).toEqual({ active_file: "auth.json" });
    });
  });

  describe("updatePortConfig", () => {
    it("sends port config update", async () => {
      const mockResponse = {
        success: true,
        message: "Updated",
        config: {
          fastapi_port: 3000,
          camoufox_debug_port: 9222,
          stream_proxy_port: 3120,
          stream_proxy_enabled: true,
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const { updatePortConfig } = await import("./client");
      const result = await updatePortConfig({
        fastapi_port: 3000,
        camoufox_debug_port: 9222,
        stream_proxy_port: 3120,
        stream_proxy_enabled: true,
      });

      expect(result).toEqual(mockResponse);
    });
  });
});
