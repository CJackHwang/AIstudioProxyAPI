/**
 * Chat Reducer Tests
 * 
 * Tests the chat state management logic independently from React
 */

import { describe, it, expect, beforeEach } from 'vitest';

// Type definitions matching ChatContext
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  error?: string;
  thinkingContent?: string;
  isThinking?: boolean;
}

interface ChatState {
  messages: ChatMessage[];
}

type ChatAction =
  | { type: 'ADD_MESSAGE'; payload: ChatMessage }
  | { type: 'UPDATE_MESSAGE'; payload: { id: string; content: string } }
  | { type: 'UPDATE_THINKING'; payload: { id: string; thinkingContent: string } }
  | { type: 'SET_THINKING_DONE'; payload: { id: string } }
  | { type: 'SET_MESSAGE_CONTENT'; payload: { id: string; content: string } }
  | { type: 'SET_STREAMING'; payload: { id: string; isStreaming: boolean } }
  | { type: 'SET_ERROR'; payload: { id: string; error: string } }
  | { type: 'REMOVE_MESSAGES_FROM'; payload: string }
  | { type: 'CLEAR_MESSAGES' };

// Reducer logic extracted from ChatContext
function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'ADD_MESSAGE':
      return { ...state, messages: [...state.messages, action.payload] };
    case 'UPDATE_MESSAGE':
      return {
        ...state,
        messages: state.messages.map(m =>
          m.id === action.payload.id
            ? { ...m, content: m.content + action.payload.content }
            : m
        ),
      };
    case 'UPDATE_THINKING':
      return {
        ...state,
        messages: state.messages.map(m =>
          m.id === action.payload.id
            ? { 
                ...m, 
                thinkingContent: (m.thinkingContent || '') + action.payload.thinkingContent,
                isThinking: true,
              }
            : m
        ),
      };
    case 'SET_THINKING_DONE':
      return {
        ...state,
        messages: state.messages.map(m =>
          m.id === action.payload.id
            ? { ...m, isThinking: false }
            : m
        ),
      };
    case 'SET_MESSAGE_CONTENT':
      return {
        ...state,
        messages: state.messages.map(m =>
          m.id === action.payload.id
            ? { ...m, content: action.payload.content }
            : m
        ),
      };
    case 'SET_STREAMING':
      return {
        ...state,
        messages: state.messages.map(m =>
          m.id === action.payload.id
            ? { ...m, isStreaming: action.payload.isStreaming }
            : m
        ),
      };
    case 'SET_ERROR':
      return {
        ...state,
        messages: state.messages.map(m =>
          m.id === action.payload.id
            ? { ...m, error: action.payload.error, isStreaming: false, isThinking: false }
            : m
        ),
      };
    case 'REMOVE_MESSAGES_FROM': {
      const index = state.messages.findIndex(m => m.id === action.payload);
      if (index === -1) return state;
      return { messages: state.messages.slice(0, index) };
    }
    case 'CLEAR_MESSAGES':
      return { messages: [] };
    default:
      return state;
  }
}

// Helper to create test messages
function createMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: overrides.id || 'test-id',
    role: overrides.role || 'user',
    content: overrides.content || 'Test content',
    timestamp: overrides.timestamp || new Date(),
    ...overrides,
  };
}

describe('chatReducer', () => {
  let initialState: ChatState;

  beforeEach(() => {
    initialState = { messages: [] };
  });

  describe('ADD_MESSAGE', () => {
    it('adds message to empty state', () => {
      const message = createMessage({ id: 'msg-1', content: 'Hello' });
      const result = chatReducer(initialState, { type: 'ADD_MESSAGE', payload: message });
      
      expect(result.messages).toHaveLength(1);
      expect(result.messages[0].content).toBe('Hello');
    });

    it('appends message to existing messages', () => {
      const stateWithMessage = { messages: [createMessage({ id: 'msg-1' })] };
      const newMessage = createMessage({ id: 'msg-2', content: 'New message' });
      
      const result = chatReducer(stateWithMessage, { type: 'ADD_MESSAGE', payload: newMessage });
      
      expect(result.messages).toHaveLength(2);
      expect(result.messages[1].id).toBe('msg-2');
    });

    it('preserves message properties', () => {
      const message = createMessage({
        id: 'msg-1',
        role: 'assistant',
        content: 'Response',
        isStreaming: true,
        thinkingContent: 'Thinking...',
      });
      
      const result = chatReducer(initialState, { type: 'ADD_MESSAGE', payload: message });
      
      expect(result.messages[0].role).toBe('assistant');
      expect(result.messages[0].isStreaming).toBe(true);
      expect(result.messages[0].thinkingContent).toBe('Thinking...');
    });
  });

  describe('UPDATE_MESSAGE', () => {
    it('appends content to existing message', () => {
      const stateWithMessage = { 
        messages: [createMessage({ id: 'msg-1', content: 'Hello' })] 
      };
      
      const result = chatReducer(stateWithMessage, {
        type: 'UPDATE_MESSAGE',
        payload: { id: 'msg-1', content: ' World' },
      });
      
      expect(result.messages[0].content).toBe('Hello World');
    });

    it('does not affect other messages', () => {
      const stateWithMessages = {
        messages: [
          createMessage({ id: 'msg-1', content: 'First' }),
          createMessage({ id: 'msg-2', content: 'Second' }),
        ],
      };
      
      const result = chatReducer(stateWithMessages, {
        type: 'UPDATE_MESSAGE',
        payload: { id: 'msg-1', content: ' updated' },
      });
      
      expect(result.messages[0].content).toBe('First updated');
      expect(result.messages[1].content).toBe('Second');
    });

    it('handles non-existent message gracefully', () => {
      const stateWithMessage = { messages: [createMessage({ id: 'msg-1' })] };
      
      const result = chatReducer(stateWithMessage, {
        type: 'UPDATE_MESSAGE',
        payload: { id: 'non-existent', content: 'test' },
      });
      
      expect(result.messages).toEqual(stateWithMessage.messages);
    });
  });

  describe('UPDATE_THINKING', () => {
    it('adds thinking content and sets isThinking', () => {
      const stateWithMessage = { 
        messages: [createMessage({ id: 'msg-1', role: 'assistant' })] 
      };
      
      const result = chatReducer(stateWithMessage, {
        type: 'UPDATE_THINKING',
        payload: { id: 'msg-1', thinkingContent: 'Let me think...' },
      });
      
      expect(result.messages[0].thinkingContent).toBe('Let me think...');
      expect(result.messages[0].isThinking).toBe(true);
    });

    it('appends to existing thinking content', () => {
      const stateWithThinking = {
        messages: [createMessage({ id: 'msg-1', thinkingContent: 'First ' })],
      };
      
      const result = chatReducer(stateWithThinking, {
        type: 'UPDATE_THINKING',
        payload: { id: 'msg-1', thinkingContent: 'Second' },
      });
      
      expect(result.messages[0].thinkingContent).toBe('First Second');
    });

    it('handles undefined thinkingContent', () => {
      const stateWithMessage = { messages: [createMessage({ id: 'msg-1' })] };
      
      const result = chatReducer(stateWithMessage, {
        type: 'UPDATE_THINKING',
        payload: { id: 'msg-1', thinkingContent: 'New thinking' },
      });
      
      expect(result.messages[0].thinkingContent).toBe('New thinking');
    });
  });

  describe('SET_THINKING_DONE', () => {
    it('sets isThinking to false', () => {
      const stateWithThinking = {
        messages: [createMessage({ id: 'msg-1', isThinking: true, thinkingContent: 'Done' })],
      };
      
      const result = chatReducer(stateWithThinking, {
        type: 'SET_THINKING_DONE',
        payload: { id: 'msg-1' },
      });
      
      expect(result.messages[0].isThinking).toBe(false);
      expect(result.messages[0].thinkingContent).toBe('Done'); // Preserves content
    });
  });

  describe('SET_MESSAGE_CONTENT', () => {
    it('replaces entire content', () => {
      const stateWithMessage = { 
        messages: [createMessage({ id: 'msg-1', content: 'Original' })] 
      };
      
      const result = chatReducer(stateWithMessage, {
        type: 'SET_MESSAGE_CONTENT',
        payload: { id: 'msg-1', content: 'Replaced' },
      });
      
      expect(result.messages[0].content).toBe('Replaced');
    });

    it('allows setting empty content', () => {
      const stateWithMessage = { 
        messages: [createMessage({ id: 'msg-1', content: 'Has content' })] 
      };
      
      const result = chatReducer(stateWithMessage, {
        type: 'SET_MESSAGE_CONTENT',
        payload: { id: 'msg-1', content: '' },
      });
      
      expect(result.messages[0].content).toBe('');
    });
  });

  describe('SET_STREAMING', () => {
    it('sets isStreaming to true', () => {
      const stateWithMessage = { 
        messages: [createMessage({ id: 'msg-1', isStreaming: false })] 
      };
      
      const result = chatReducer(stateWithMessage, {
        type: 'SET_STREAMING',
        payload: { id: 'msg-1', isStreaming: true },
      });
      
      expect(result.messages[0].isStreaming).toBe(true);
    });

    it('sets isStreaming to false', () => {
      const stateWithMessage = { 
        messages: [createMessage({ id: 'msg-1', isStreaming: true })] 
      };
      
      const result = chatReducer(stateWithMessage, {
        type: 'SET_STREAMING',
        payload: { id: 'msg-1', isStreaming: false },
      });
      
      expect(result.messages[0].isStreaming).toBe(false);
    });
  });

  describe('SET_ERROR', () => {
    it('sets error message', () => {
      const stateWithMessage = { 
        messages: [createMessage({ id: 'msg-1', isStreaming: true })] 
      };
      
      const result = chatReducer(stateWithMessage, {
        type: 'SET_ERROR',
        payload: { id: 'msg-1', error: 'Connection failed' },
      });
      
      expect(result.messages[0].error).toBe('Connection failed');
    });

    it('also sets isStreaming to false', () => {
      const stateWithMessage = { 
        messages: [createMessage({ id: 'msg-1', isStreaming: true })] 
      };
      
      const result = chatReducer(stateWithMessage, {
        type: 'SET_ERROR',
        payload: { id: 'msg-1', error: 'Error' },
      });
      
      expect(result.messages[0].isStreaming).toBe(false);
    });

    it('also sets isThinking to false', () => {
      const stateWithThinking = { 
        messages: [createMessage({ id: 'msg-1', isStreaming: true, isThinking: true })] 
      };
      
      const result = chatReducer(stateWithThinking, {
        type: 'SET_ERROR',
        payload: { id: 'msg-1', error: 'Error' },
      });
      
      expect(result.messages[0].isThinking).toBe(false);
    });
  });

  describe('REMOVE_MESSAGES_FROM', () => {
    it('removes message and all following', () => {
      const stateWithMessages = {
        messages: [
          createMessage({ id: 'msg-1' }),
          createMessage({ id: 'msg-2' }),
          createMessage({ id: 'msg-3' }),
        ],
      };
      
      const result = chatReducer(stateWithMessages, {
        type: 'REMOVE_MESSAGES_FROM',
        payload: 'msg-2',
      });
      
      expect(result.messages).toHaveLength(1);
      expect(result.messages[0].id).toBe('msg-1');
    });

    it('removes first message and all others', () => {
      const stateWithMessages = {
        messages: [
          createMessage({ id: 'msg-1' }),
          createMessage({ id: 'msg-2' }),
        ],
      };
      
      const result = chatReducer(stateWithMessages, {
        type: 'REMOVE_MESSAGES_FROM',
        payload: 'msg-1',
      });
      
      expect(result.messages).toHaveLength(0);
    });

    it('returns unchanged state for non-existent id', () => {
      const stateWithMessages = {
        messages: [createMessage({ id: 'msg-1' })],
      };
      
      const result = chatReducer(stateWithMessages, {
        type: 'REMOVE_MESSAGES_FROM',
        payload: 'non-existent',
      });
      
      expect(result).toBe(stateWithMessages);
    });
  });

  describe('CLEAR_MESSAGES', () => {
    it('clears all messages', () => {
      const stateWithMessages = {
        messages: [
          createMessage({ id: 'msg-1' }),
          createMessage({ id: 'msg-2' }),
          createMessage({ id: 'msg-3' }),
        ],
      };
      
      const result = chatReducer(stateWithMessages, { type: 'CLEAR_MESSAGES' });
      
      expect(result.messages).toHaveLength(0);
    });

    it('works on empty state', () => {
      const result = chatReducer(initialState, { type: 'CLEAR_MESSAGES' });
      
      expect(result.messages).toHaveLength(0);
    });
  });

  describe('Immutability', () => {
    it('does not mutate original state', () => {
      const originalMessages = [createMessage({ id: 'msg-1', content: 'Original' })];
      const state = { messages: originalMessages };
      
      chatReducer(state, {
        type: 'UPDATE_MESSAGE',
        payload: { id: 'msg-1', content: ' Added' },
      });
      
      expect(originalMessages[0].content).toBe('Original');
    });

    it('creates new message array on add', () => {
      const result = chatReducer(initialState, {
        type: 'ADD_MESSAGE',
        payload: createMessage(),
      });
      
      expect(result.messages).not.toBe(initialState.messages);
    });
  });

  describe('Unknown action', () => {
    it('returns current state for unknown action', () => {
      const state = { messages: [createMessage()] };
      
      // @ts-expect-error Testing unknown action type
      const result = chatReducer(state, { type: 'UNKNOWN_ACTION' });
      
      expect(result).toBe(state);
    });
  });
});
