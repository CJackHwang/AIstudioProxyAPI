/**
 * UI-specific Types
 */

// Chat UI Message (extends API message with UI state)
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  error?: string;
  /** Accumulated thinking/reasoning content from model */
  thinkingContent?: string;
  /** True while model is actively outputting thinking content */
  isThinking?: boolean;
}

// Model Settings (persisted to localStorage)
export interface ModelSettings {
  temperature: number;
  maxOutputTokens: number;
  topP: number;
  thinkingLevel: string;
  enableThinking: boolean;
  enableManualBudget: boolean;
  thinkingBudget: number;
  enableGoogleSearch: boolean;
  systemPrompt: string;
  stopSequences: string[];
}

// Theme
export type Theme = 'light' | 'dark';

// Sidebar State
export interface SidebarState {
  leftOpen: boolean;
  rightOpen: boolean;
}

// WebSocket Connection Status
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';
