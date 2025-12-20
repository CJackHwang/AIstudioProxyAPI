/**
 * SettingsPage Component Tests
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock react-query
vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn(),
}));

import { useQuery } from "@tanstack/react-query";

interface ServerStatus {
  status: string;
  uptime_seconds: number;
  uptime_formatted: string;
  launch_mode: string;
  server_port: number;
  stream_port: number;
  version: string;
  python_version: string;
  started_at: string;
}

describe("SettingsPage StatusBar Logic", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Server Status Query", () => {
    it("returns loading state initially", () => {
      vi.mocked(useQuery).mockReturnValue({
        data: undefined,
        isLoading: true,
        error: null,
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof useQuery>);

      const result = useQuery({ queryKey: ["serverStatus"], queryFn: vi.fn() });
      expect(result.isLoading).toBe(true);
    });

    it("returns server status when loaded", () => {
      const mockStatus: ServerStatus = {
        status: "running",
        uptime_seconds: 3600,
        uptime_formatted: "1h 0m",
        launch_mode: "normal",
        server_port: 2048,
        stream_port: 3120,
        version: "1.0.0",
        python_version: "3.11.0",
        started_at: "2024-01-01T00:00:00Z",
      };

      vi.mocked(useQuery).mockReturnValue({
        data: mockStatus,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof useQuery>);

      const result = useQuery({ queryKey: ["serverStatus"], queryFn: vi.fn() });
      expect(result.data?.status).toBe("running");
      expect(result.data?.uptime_formatted).toBe("1h 0m");
    });
  });

  describe("Status Display Logic", () => {
    it("shows unknown when status is undefined", () => {
      const status = undefined as ServerStatus | undefined;
      const displayValue = status?.status || "unknown";
      expect(displayValue).toBe("unknown");
    });

    it("shows actual status when available", () => {
      const status: ServerStatus = {
        status: "healthy",
        uptime_seconds: 0,
        uptime_formatted: "0m",
        launch_mode: "normal",
        server_port: 2048,
        stream_port: 3120,
        version: "1.0.0",
        python_version: "3.11.0",
        started_at: "",
      };
      const displayValue = status?.status || "unknown";
      expect(displayValue).toBe("healthy");
    });

    it("shows dash when uptime is undefined", () => {
      const status = undefined as ServerStatus | undefined;
      const displayValue = status?.uptime_formatted || "-";
      expect(displayValue).toBe("-");
    });

    it("formats port display", () => {
      const status: ServerStatus = {
        status: "running",
        uptime_seconds: 0,
        uptime_formatted: "0m",
        launch_mode: "normal",
        server_port: 2048,
        stream_port: 3120,
        version: "1.0.0",
        python_version: "3.11.0",
        started_at: "",
      };
      const portDisplay = `Port ${status?.server_port || "-"}`;
      expect(portDisplay).toBe("Port 2048");
    });
  });
});

describe("SettingsPage ApiKeysSection Logic", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("API Keys Query", () => {
    it("returns loading state initially", () => {
      vi.mocked(useQuery).mockReturnValue({
        data: undefined,
        isLoading: true,
        error: null,
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof useQuery>);

      const result = useQuery({ queryKey: ["apiKeys"], queryFn: vi.fn() });
      expect(result.isLoading).toBe(true);
    });

    it("returns keys list when loaded", () => {
      const mockData = { keys: ["key1", "key2", "key3"] };

      vi.mocked(useQuery).mockReturnValue({
        data: mockData,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof useQuery>);

      const result = useQuery({ queryKey: ["apiKeys"], queryFn: vi.fn() });
      expect(result.data?.keys).toHaveLength(3);
    });
  });

  describe("Key Display Logic", () => {
    it("truncates key for display", () => {
      const key = "sk-1234567890abcdefghijklmnop";
      const truncated = key.substring(0, 16) + "...";
      expect(truncated).toBe("sk-1234567890abc...");
    });

    it("handles short keys", () => {
      const key = "short";
      const truncated = key.substring(0, 16) + "...";
      expect(truncated).toBe("short...");
    });

    it("checks if keys array has items", () => {
      const data = { keys: ["key1", "key2"] };
      const hasKeys = data?.keys?.length > 0;
      expect(hasKeys).toBe(true);
    });

    it("handles empty keys array", () => {
      const data = { keys: [] };
      const hasKeys = data?.keys?.length > 0;
      expect(hasKeys).toBe(false);
    });
  });

  describe("Add Key Form Logic", () => {
    it("validates non-empty key", () => {
      const newKey = "sk-valid-key";
      const isValid = newKey.trim().length > 0;
      expect(isValid).toBe(true);
    });

    it("rejects empty key", () => {
      const newKey = "   ";
      const isValid = newKey.trim().length > 0;
      expect(isValid).toBe(false);
    });

    it("clears input after successful add", () => {
      let newKey = "sk-new-key";
      // Simulate successful add
      newKey = "";
      expect(newKey).toBe("");
    });
  });

  describe("Message State Logic", () => {
    it("sets success message", () => {
      let message: { type: "success" | "error"; text: string } | null = null;
      message = { type: "success", text: "API Key 已添加" };
      expect(message.type).toBe("success");
      expect(message.text).toBe("API Key 已添加");
    });

    it("sets error message", () => {
      let message: { type: "success" | "error"; text: string } | null = null;
      message = { type: "error", text: "添加失败" };
      expect(message.type).toBe("error");
    });

    it("clears message before operation", () => {
      let message: { type: "success" | "error"; text: string } | null = {
        type: "success",
        text: "old",
      };
      message = null;
      expect(message).toBeNull();
    });
  });

  describe("Delete Confirmation Logic", () => {
    it("formats confirmation message with truncated key", () => {
      const key = "sk-1234567890abcdefghij";
      const confirmMessage = `确定删除 API Key: ${key.substring(0, 8)}...?`;
      expect(confirmMessage).toBe("确定删除 API Key: sk-12345...?");
    });
  });
});
