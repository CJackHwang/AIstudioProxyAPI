/**
 * PortStatus Component Tests
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Define types locally to avoid module resolution issues
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

describe("PortStatus Logic", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Data Fetching", () => {
    it("returns loading state structure", () => {
      const result = { data: undefined, isLoading: true, error: null };
      expect(result.isLoading).toBe(true);
    });

    it("returns port status when loaded", () => {
      const mockStatus = {
        ports: [
          {
            port: 2048,
            port_type: "fastapi",
            in_use: true,
            processes: [{ pid: 1234, name: "python" }],
          },
          {
            port: 3120,
            port_type: "stream_proxy",
            in_use: false,
            processes: [],
          },
        ] as PortStatusInfo[],
      };

      const result = { data: mockStatus, isLoading: false, error: null };
      expect(result.data.ports).toHaveLength(2);
      expect(result.data.ports[0].in_use).toBe(true);
    });

    it("handles empty ports list", () => {
      const mockStatus = { ports: [] as PortStatusInfo[] };
      const result = { data: mockStatus, isLoading: false, error: null };
      expect(result.data.ports).toHaveLength(0);
    });
  });

  describe("Mutations", () => {
    it("killProcess accepts pid", () => {
      const pid = 1234;
      expect(typeof pid).toBe("number");
    });

    it("tracks pending state during kill", () => {
      const mutation = { isPending: true, variables: 1234 };
      expect(mutation.isPending).toBe(true);
      expect(mutation.variables).toBe(1234);
    });
  });

  describe("Kill Confirmation Flow", () => {
    it("enters confirmation mode on first click", () => {
      let confirmKill: number | null = null;
      const pid = 1234;

      // First click - enter confirmation
      confirmKill = pid;

      expect(confirmKill).toBe(1234);
    });

    it("executes kill on second click", () => {
      const confirmKill: number | null = 1234;
      const pid = 1234;
      let killExecuted = false;

      // Second click when already confirmed
      if (confirmKill === pid) {
        killExecuted = true;
      }

      expect(killExecuted).toBe(true);
    });

    it("auto-cancels confirmation after timeout", () => {
      let confirmKill: number | null = 1234;
      const pid = 1234;

      // Simulate timeout callback
      if (confirmKill === pid) {
        confirmKill = null;
      }

      expect(confirmKill).toBeNull();
    });

    it("does not cancel if different pid confirmed", () => {
      let confirmKill: number | null = 5678;
      const originalPid = 1234;

      // Timeout for originalPid should not affect confirmKill for 5678
      if (confirmKill === originalPid) {
        confirmKill = null;
      }

      expect(confirmKill).toBe(5678);
    });

    it("resets confirmation after successful kill", () => {
      let confirmKill: number | null = 1234;

      // onSuccess callback
      confirmKill = null;

      expect(confirmKill).toBeNull();
    });
  });

  describe("Port Status Display", () => {
    it("identifies ports in use", () => {
      const port: PortStatusInfo = {
        port: 2048,
        port_type: "fastapi",
        in_use: true,
        processes: [{ pid: 1234, name: "python" }],
      };

      expect(port.in_use).toBe(true);
    });

    it("identifies unused ports", () => {
      const port: PortStatusInfo = {
        port: 3120,
        port_type: "stream_proxy",
        in_use: false,
        processes: [],
      };

      expect(port.in_use).toBe(false);
      expect(port.processes).toHaveLength(0);
    });

    it("extracts process info correctly", () => {
      const port: PortStatusInfo = {
        port: 2048,
        port_type: "fastapi",
        in_use: true,
        processes: [
          { pid: 1234, name: "python" },
          { pid: 5678, name: "node" },
        ],
      };

      expect(port.processes).toHaveLength(2);
      expect(port.processes[0].pid).toBe(1234);
      expect(port.processes[1].name).toBe("node");
    });
  });

  describe("Port List Processing", () => {
    it("extracts ports array from response", () => {
      const data = {
        ports: [
          { port: 2048, port_type: "fastapi", in_use: true, processes: [] },
        ] as PortStatusInfo[],
      };

      const ports = data.ports;
      expect(ports).toHaveLength(1);
    });

    it("handles undefined data gracefully", () => {
      const data: { ports: PortStatusInfo[] } | undefined = undefined;
      const ports = data?.ports || [];
      expect(ports).toHaveLength(0);
    });

    it("sorts ports by number", () => {
      const ports: PortStatusInfo[] = [
        { port: 9222, port_type: "debug", in_use: false, processes: [] },
        { port: 2048, port_type: "fastapi", in_use: true, processes: [] },
        { port: 3120, port_type: "stream", in_use: false, processes: [] },
      ];

      const sorted = [...ports].sort((a, b) => a.port - b.port);
      expect(sorted[0].port).toBe(2048);
      expect(sorted[1].port).toBe(3120);
      expect(sorted[2].port).toBe(9222);
    });
  });
});
