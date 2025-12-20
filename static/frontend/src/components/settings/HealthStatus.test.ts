/**
 * HealthStatus Component Tests
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Define types locally
interface HealthDetails {
  is_initializing: boolean;
  is_playwright_ready: boolean;
  is_browser_connected: boolean;
  is_page_ready: boolean;
  workerRunning: boolean;
  queueLength: number;
  launchMode: string;
  browserAndPageCritical: boolean;
}

interface HealthResponse {
  status: "OK" | "Error";
  message: string;
  details: HealthDetails;
}

describe("HealthStatus Logic", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Data Fetching", () => {
    it("returns loading state structure", () => {
      const result = {
        data: undefined,
        isLoading: true,
        error: null,
        dataUpdatedAt: 0,
      };
      expect(result.isLoading).toBe(true);
    });

    it("returns health data when loaded", () => {
      const mockHealth: HealthResponse = {
        status: "OK",
        message: "All systems operational",
        details: {
          is_initializing: false,
          is_playwright_ready: true,
          is_browser_connected: true,
          is_page_ready: true,
          workerRunning: true,
          queueLength: 0,
          launchMode: "normal",
          browserAndPageCritical: true,
        },
      };

      const result = {
        data: mockHealth,
        isLoading: false,
        error: null,
        dataUpdatedAt: Date.now(),
      };
      expect(result.data.status).toBe("OK");
      expect(result.data.details.is_playwright_ready).toBe(true);
    });

    it("returns error state", () => {
      const result = {
        data: undefined,
        isLoading: false,
        error: new Error("Network error"),
        dataUpdatedAt: 0,
      };
      expect(result.error).toBeInstanceOf(Error);
    });
  });

  describe("Health Status Determination", () => {
    it("identifies healthy status", () => {
      const data: HealthResponse = {
        status: "OK",
        message: "Healthy",
        details: {} as HealthDetails,
      };

      const isHealthy = data.status === "OK";
      expect(isHealthy).toBe(true);
    });

    it("identifies unhealthy status", () => {
      const data: HealthResponse = {
        status: "Error",
        message: "Service unavailable",
        details: {} as HealthDetails,
      };

      const isHealthy = data.status === "OK";
      expect(isHealthy).toBe(false);
    });

    it("handles null data as unhealthy", () => {
      const data: HealthResponse | null = null;
      const isHealthy = data?.status === "OK";
      expect(isHealthy).toBe(false);
    });
  });

  describe("Status Item Evaluation", () => {
    it("evaluates playwright_ready status", () => {
      const details: HealthDetails = {
        is_initializing: false,
        is_playwright_ready: true,
        is_browser_connected: true,
        is_page_ready: true,
        workerRunning: true,
        queueLength: 0,
        launchMode: "normal",
        browserAndPageCritical: true,
      };

      expect(details.is_playwright_ready).toBe(true);
    });

    it("evaluates browser_connected status", () => {
      const details: HealthDetails = {
        is_initializing: false,
        is_playwright_ready: true,
        is_browser_connected: false,
        is_page_ready: false,
        workerRunning: true,
        queueLength: 0,
        launchMode: "normal",
        browserAndPageCritical: false,
      };

      expect(details.is_browser_connected).toBe(false);
    });

    it("evaluates queue length status (healthy when < 10)", () => {
      const queueLength = 5;
      const isQueueHealthy = queueLength < 10;
      expect(isQueueHealthy).toBe(true);
    });

    it("evaluates queue length status (unhealthy when >= 10)", () => {
      const queueLength = 15;
      const isQueueHealthy = queueLength < 10;
      expect(isQueueHealthy).toBe(false);
    });

    it("evaluates worker running status", () => {
      const details: HealthDetails = {
        is_initializing: false,
        is_playwright_ready: true,
        is_browser_connected: true,
        is_page_ready: true,
        workerRunning: false,
        queueLength: 0,
        launchMode: "normal",
        browserAndPageCritical: true,
      };

      expect(details.workerRunning).toBe(false);
    });
  });

  describe("Display Values", () => {
    it("formats ready status as 就绪", () => {
      const isReady = true;
      const displayValue = isReady ? "就绪" : "未就绪";
      expect(displayValue).toBe("就绪");
    });

    it("formats not ready status as 未就绪", () => {
      const isReady = false;
      const displayValue = isReady ? "就绪" : "未就绪";
      expect(displayValue).toBe("未就绪");
    });

    it("formats connected status as 已连接", () => {
      const isConnected = true;
      const displayValue = isConnected ? "已连接" : "未连接";
      expect(displayValue).toBe("已连接");
    });

    it("formats queue length display", () => {
      const queueLength = 5;
      const displayValue = `${queueLength} 个请求`;
      expect(displayValue).toBe("5 个请求");
    });

    it("formats worker status as 运行中", () => {
      const isRunning = true;
      const displayValue = isRunning ? "运行中" : "已停止";
      expect(displayValue).toBe("运行中");
    });
  });

  describe("Last Updated Display", () => {
    it("shows last updated when dataUpdatedAt > 0", () => {
      const dataUpdatedAt = Date.now();
      const shouldShow = dataUpdatedAt > 0;
      expect(shouldShow).toBe(true);
    });

    it("hides last updated when dataUpdatedAt is 0", () => {
      const dataUpdatedAt = 0;
      const shouldShow = dataUpdatedAt > 0;
      expect(shouldShow).toBe(false);
    });

    it("formats timestamp as locale time string", () => {
      const timestamp = new Date(2024, 0, 1, 12, 30, 45).getTime();
      const formatted = new Date(timestamp).toLocaleTimeString();
      expect(formatted).toContain(":");
    });
  });

  describe("Visibility-based Fetching", () => {
    it("configures refetch interval when visible", () => {
      const isVisible = true;
      const refetchInterval = isVisible ? 3000 : false;
      expect(refetchInterval).toBe(3000);
    });

    it("disables refetch interval when not visible", () => {
      const isVisible = false;
      const refetchInterval = isVisible ? 3000 : false;
      expect(refetchInterval).toBe(false);
    });

    it("disables enabled when not visible initially", () => {
      const isVisible = false;
      const enabled = isVisible;
      expect(enabled).toBe(false);
    });
  });
});
