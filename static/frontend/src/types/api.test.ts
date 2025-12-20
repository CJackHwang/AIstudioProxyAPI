/**
 * API Types Tests
 * 
 * Type validation and structural tests
 */

import { describe, it, expect } from 'vitest';
import type { 
  Message, 
  ChatCompletionRequest, 
  ChatCompletionResponse,
  ChatCompletionChunk,
  ThinkingLevel,
  Model,
  ModelsResponse,
  HealthStatus,
  LogEntry
} from './api';

describe('Message Type', () => {
  it('accepts valid user message', () => {
    const message: Message = {
      role: 'user',
      content: 'Hello, how are you?',
    };
    expect(message.role).toBe('user');
    expect(message.content).toBe('Hello, how are you?');
  });

  it('accepts valid assistant message', () => {
    const message: Message = {
      role: 'assistant',
      content: 'I am doing well, thank you!',
    };
    expect(message.role).toBe('assistant');
  });

  it('accepts valid system message', () => {
    const message: Message = {
      role: 'system',
      content: 'You are a helpful assistant.',
    };
    expect(message.role).toBe('system');
  });
});

describe('ChatCompletionRequest Type', () => {
  it('requires model and messages', () => {
    const request: ChatCompletionRequest = {
      model: 'gemini-2.5-pro',
      messages: [{ role: 'user', content: 'Hi' }],
    };
    expect(request.model).toBe('gemini-2.5-pro');
    expect(request.messages).toHaveLength(1);
  });

  it('accepts optional parameters', () => {
    const request: ChatCompletionRequest = {
      model: 'gemini-2.5-pro',
      messages: [{ role: 'user', content: 'Hi' }],
      temperature: 0.8,
      max_output_tokens: 4096,
      top_p: 0.95,
      stop: ['###'],
      reasoning_effort: 'high',
      stream: true,
    };
    expect(request.temperature).toBe(0.8);
    expect(request.max_output_tokens).toBe(4096);
    expect(request.reasoning_effort).toBe('high');
  });

  it('accepts numeric reasoning_effort', () => {
    const request: ChatCompletionRequest = {
      model: 'gemini-2.5-pro',
      messages: [{ role: 'user', content: 'Hi' }],
      reasoning_effort: 8192,
    };
    expect(request.reasoning_effort).toBe(8192);
  });

  it('accepts google_search tool', () => {
    const request: ChatCompletionRequest = {
      model: 'gemini-2.5-pro',
      messages: [{ role: 'user', content: 'Search for news' }],
      tools: [{ type: 'google_search', google_search_retrieval: {} }],
    };
    expect(request.tools?.[0].type).toBe('google_search');
  });
});

describe('ChatCompletionResponse Type', () => {
  it('has correct structure', () => {
    const response: ChatCompletionResponse = {
      id: 'chatcmpl-abc123',
      object: 'chat.completion',
      created: 1700000000,
      model: 'gemini-2.5-pro',
      choices: [{
        index: 0,
        message: { role: 'assistant', content: 'Hello!' },
        finish_reason: 'stop',
      }],
      usage: {
        prompt_tokens: 10,
        completion_tokens: 5,
        total_tokens: 15,
      },
    };
    
    expect(response.object).toBe('chat.completion');
    expect(response.choices).toHaveLength(1);
    expect(response.choices[0].finish_reason).toBe('stop');
  });

  it('allows null finish_reason', () => {
    const response: ChatCompletionResponse = {
      id: 'chatcmpl-abc123',
      object: 'chat.completion',
      created: 1700000000,
      model: 'gemini-2.5-pro',
      choices: [{
        index: 0,
        message: { role: 'assistant', content: '' },
        finish_reason: null,
      }],
    };
    expect(response.choices[0].finish_reason).toBeNull();
  });
});

describe('ChatCompletionChunk Type', () => {
  it('has streaming chunk structure', () => {
    const chunk: ChatCompletionChunk = {
      id: 'chatcmpl-abc123',
      object: 'chat.completion.chunk',
      created: 1700000000,
      model: 'gemini-2.5-pro',
      choices: [{
        index: 0,
        delta: { content: 'Hello' },
        finish_reason: null,
      }],
    };
    
    expect(chunk.object).toBe('chat.completion.chunk');
    expect(chunk.choices[0].delta.content).toBe('Hello');
  });

  it('supports reasoning_content in delta', () => {
    const chunk: ChatCompletionChunk = {
      id: 'chatcmpl-abc123',
      object: 'chat.completion.chunk',
      created: 1700000000,
      model: 'gemini-2.5-pro',
      choices: [{
        index: 0,
        delta: { reasoning_content: 'Let me think...' },
        finish_reason: null,
      }],
    };
    
    expect(chunk.choices[0].delta.reasoning_content).toBe('Let me think...');
  });
});

describe('ThinkingLevel Type', () => {
  it('accepts all valid values', () => {
    const levels: ThinkingLevel[] = ['minimal', 'low', 'medium', 'high'];
    levels.forEach(level => {
      expect(['minimal', 'low', 'medium', 'high']).toContain(level);
    });
  });
});

describe('Model Type', () => {
  it('has correct structure', () => {
    const model: Model = {
      id: 'gemini-2.5-pro',
      object: 'model',
      created: 1700000000,
      owned_by: 'google',
      default_temperature: 1.0,
      default_max_output_tokens: 8192,
      supported_max_output_tokens: 65536,
      default_top_p: 0.95,
    };
    
    expect(model.object).toBe('model');
    expect(model.owned_by).toBe('google');
  });
});

describe('ModelsResponse Type', () => {
  it('has list structure', () => {
    const response: ModelsResponse = {
      object: 'list',
      data: [
        { id: 'gemini-2.5-pro', object: 'model', created: 1700000000, owned_by: 'google' },
        { id: 'gemini-2.5-flash', object: 'model', created: 1700000000, owned_by: 'google' },
      ],
    };
    
    expect(response.object).toBe('list');
    expect(response.data).toHaveLength(2);
  });
});

describe('HealthStatus Type', () => {
  it('accepts healthy status', () => {
    const status: HealthStatus = {
      status: 'healthy',
      browser_connected: true,
      page_ready: true,
    };
    expect(status.status).toBe('healthy');
  });

  it('accepts degraded status', () => {
    const status: HealthStatus = {
      status: 'degraded',
      browser_connected: true,
      page_ready: false,
    };
    expect(status.status).toBe('degraded');
  });

  it('accepts unhealthy status', () => {
    const status: HealthStatus = {
      status: 'unhealthy',
      browser_connected: false,
      page_ready: false,
    };
    expect(status.status).toBe('unhealthy');
  });
});

describe('LogEntry Type', () => {
  it('accepts DEBUG level', () => {
    const entry: LogEntry = {
      timestamp: '2024-01-01T00:00:00Z',
      level: 'DBG',
      source: 'browser',
      message: 'Debug message',
    };
    expect(entry.level).toBe('DBG');
  });

  it('accepts INFO level', () => {
    const entry: LogEntry = {
      timestamp: '2024-01-01T00:00:00Z',
      level: 'INF',
      source: 'api',
      message: 'Info message',
    };
    expect(entry.level).toBe('INF');
  });

  it('accepts WARNING level', () => {
    const entry: LogEntry = {
      timestamp: '2024-01-01T00:00:00Z',
      level: 'WRN',
      source: 'system',
      message: 'Warning message',
    };
    expect(entry.level).toBe('WRN');
  });

  it('accepts ERROR level', () => {
    const entry: LogEntry = {
      timestamp: '2024-01-01T00:00:00Z',
      level: 'ERR',
      source: 'error',
      message: 'Error message',
    };
    expect(entry.level).toBe('ERR');
  });
});
