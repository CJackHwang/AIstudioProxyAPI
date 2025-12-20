/**
 * UI Types Tests
 * 
 * Type validation for UI-specific types
 */

import { describe, it, expect } from 'vitest';
import type { 
  ChatMessage, 
  ModelSettings, 
  Theme, 
  SidebarState, 
  ConnectionStatus 
} from './ui';

describe('ChatMessage Type', () => {
  it('accepts valid user message', () => {
    const message: ChatMessage = {
      id: 'msg-123',
      role: 'user',
      content: 'Hello, how are you?',
      timestamp: new Date(),
    };
    
    expect(message.id).toBe('msg-123');
    expect(message.role).toBe('user');
  });

  it('accepts valid assistant message with streaming', () => {
    const message: ChatMessage = {
      id: 'msg-456',
      role: 'assistant',
      content: 'I am doing well.',
      timestamp: new Date(),
      isStreaming: true,
    };
    
    expect(message.isStreaming).toBe(true);
  });

  it('accepts message with thinking content', () => {
    const message: ChatMessage = {
      id: 'msg-789',
      role: 'assistant',
      content: 'Final answer',
      timestamp: new Date(),
      thinkingContent: 'Let me think about this...',
      isThinking: false,
    };
    
    expect(message.thinkingContent).toBe('Let me think about this...');
    expect(message.isThinking).toBe(false);
  });

  it('accepts message with error', () => {
    const message: ChatMessage = {
      id: 'msg-err',
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      error: 'Connection failed',
    };
    
    expect(message.error).toBe('Connection failed');
  });

  it('accepts system message', () => {
    const message: ChatMessage = {
      id: 'msg-sys',
      role: 'system',
      content: 'You are a helpful assistant.',
      timestamp: new Date(),
    };
    
    expect(message.role).toBe('system');
  });
});

describe('ModelSettings Type', () => {
  it('has all required fields', () => {
    const settings: ModelSettings = {
      temperature: 1.0,
      maxOutputTokens: 8192,
      topP: 0.95,
      thinkingLevel: 'high',
      enableThinking: true,
      enableManualBudget: false,
      thinkingBudget: 8192,
      enableGoogleSearch: false,
      systemPrompt: '',
      stopSequences: [],
    };
    
    expect(settings.temperature).toBe(1.0);
    expect(settings.maxOutputTokens).toBe(8192);
    expect(settings.topP).toBe(0.95);
  });

  it('allows various thinking levels', () => {
    const levels = ['minimal', 'low', 'medium', 'high'];
    
    levels.forEach(level => {
      const settings: ModelSettings = {
        temperature: 1.0,
        maxOutputTokens: 8192,
        topP: 0.95,
        thinkingLevel: level,
        enableThinking: true,
        enableManualBudget: false,
        thinkingBudget: 8192,
        enableGoogleSearch: false,
        systemPrompt: '',
        stopSequences: [],
      };
      
      expect(settings.thinkingLevel).toBe(level);
    });
  });

  it('allows stop sequences array', () => {
    const settings: ModelSettings = {
      temperature: 1.0,
      maxOutputTokens: 8192,
      topP: 0.95,
      thinkingLevel: 'high',
      enableThinking: true,
      enableManualBudget: false,
      thinkingBudget: 8192,
      enableGoogleSearch: false,
      systemPrompt: '',
      stopSequences: ['###', '---', '\n\n'],
    };
    
    expect(settings.stopSequences).toHaveLength(3);
    expect(settings.stopSequences).toContain('###');
  });

  it('allows unicode system prompt', () => {
    const settings: ModelSettings = {
      temperature: 1.0,
      maxOutputTokens: 8192,
      topP: 0.95,
      thinkingLevel: 'high',
      enableThinking: true,
      enableManualBudget: false,
      thinkingBudget: 8192,
      enableGoogleSearch: false,
      systemPrompt: '你是一个有帮助的助手。🤖',
      stopSequences: [],
    };
    
    expect(settings.systemPrompt).toContain('你是');
    expect(settings.systemPrompt).toContain('🤖');
  });
});

describe('Theme Type', () => {
  it('accepts light theme', () => {
    const theme: Theme = 'light';
    expect(theme).toBe('light');
  });

  it('accepts dark theme', () => {
    const theme: Theme = 'dark';
    expect(theme).toBe('dark');
  });
});

describe('SidebarState Type', () => {
  it('accepts both open state', () => {
    const state: SidebarState = {
      leftOpen: true,
      rightOpen: true,
    };
    
    expect(state.leftOpen).toBe(true);
    expect(state.rightOpen).toBe(true);
  });

  it('accepts both closed state', () => {
    const state: SidebarState = {
      leftOpen: false,
      rightOpen: false,
    };
    
    expect(state.leftOpen).toBe(false);
    expect(state.rightOpen).toBe(false);
  });

  it('accepts mixed state', () => {
    const state: SidebarState = {
      leftOpen: true,
      rightOpen: false,
    };
    
    expect(state.leftOpen).toBe(true);
    expect(state.rightOpen).toBe(false);
  });
});

describe('ConnectionStatus Type', () => {
  it('accepts connecting status', () => {
    const status: ConnectionStatus = 'connecting';
    expect(status).toBe('connecting');
  });

  it('accepts connected status', () => {
    const status: ConnectionStatus = 'connected';
    expect(status).toBe('connected');
  });

  it('accepts disconnected status', () => {
    const status: ConnectionStatus = 'disconnected';
    expect(status).toBe('disconnected');
  });

  it('accepts error status', () => {
    const status: ConnectionStatus = 'error';
    expect(status).toBe('error');
  });

  it('all valid statuses are in expected set', () => {
    const validStatuses: ConnectionStatus[] = ['connecting', 'connected', 'disconnected', 'error'];
    
    validStatuses.forEach(status => {
      expect(['connecting', 'connected', 'disconnected', 'error']).toContain(status);
    });
  });
});

describe('Type Relationships', () => {
  it('ChatMessage timestamp is a Date', () => {
    const message: ChatMessage = {
      id: 'msg-1',
      role: 'user',
      content: 'test',
      timestamp: new Date('2024-01-01'),
    };
    
    expect(message.timestamp instanceof Date).toBe(true);
    expect(message.timestamp.getFullYear()).toBe(2024);
  });

  it('ModelSettings thinkingBudget is numeric', () => {
    const settings: ModelSettings = {
      temperature: 1.0,
      maxOutputTokens: 8192,
      topP: 0.95,
      thinkingLevel: 'high',
      enableThinking: true,
      enableManualBudget: true,
      thinkingBudget: 16384,
      enableGoogleSearch: false,
      systemPrompt: '',
      stopSequences: [],
    };
    
    expect(typeof settings.thinkingBudget).toBe('number');
    expect(settings.thinkingBudget).toBeGreaterThan(0);
  });
});
