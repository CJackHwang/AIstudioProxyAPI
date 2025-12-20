/**
 * Settings Reducer Tests
 * 
 * Tests the reducer logic independently from React context
 */

import { describe, it, expect, beforeEach } from 'vitest';

// Type definitions matching SettingsContext
interface ModelSettings {
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

type ThinkingLevel = 'minimal' | 'low' | 'medium' | 'high';

type SettingsAction =
  | { type: 'SET_TEMPERATURE'; payload: number }
  | { type: 'SET_MAX_TOKENS'; payload: number }
  | { type: 'SET_TOP_P'; payload: number }
  | { type: 'SET_THINKING_LEVEL'; payload: ThinkingLevel | string }
  | { type: 'SET_ENABLE_THINKING'; payload: boolean }
  | { type: 'SET_ENABLE_MANUAL_BUDGET'; payload: boolean }
  | { type: 'SET_THINKING_BUDGET'; payload: number }
  | { type: 'SET_ENABLE_GOOGLE_SEARCH'; payload: boolean }
  | { type: 'SET_SYSTEM_PROMPT'; payload: string }
  | { type: 'SET_STOP_SEQUENCES'; payload: string[] }
  | { type: 'RESET_TO_DEFAULTS' }
  | { type: 'LOAD_SETTINGS'; payload: Partial<ModelSettings> };

// Default settings matching SettingsContext
const defaultSettings: ModelSettings = {
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

// Reducer logic extracted from SettingsContext
function settingsReducer(state: ModelSettings, action: SettingsAction): ModelSettings {
  switch (action.type) {
    case 'SET_TEMPERATURE':
      return { ...state, temperature: action.payload };
    case 'SET_MAX_TOKENS':
      return { ...state, maxOutputTokens: action.payload };
    case 'SET_TOP_P':
      return { ...state, topP: action.payload };
    case 'SET_THINKING_LEVEL':
      return { ...state, thinkingLevel: action.payload };
    case 'SET_ENABLE_THINKING':
      return { ...state, enableThinking: action.payload };
    case 'SET_ENABLE_MANUAL_BUDGET':
      return { ...state, enableManualBudget: action.payload };
    case 'SET_THINKING_BUDGET':
      return { ...state, thinkingBudget: action.payload };
    case 'SET_ENABLE_GOOGLE_SEARCH':
      return { ...state, enableGoogleSearch: action.payload };
    case 'SET_SYSTEM_PROMPT':
      return { ...state, systemPrompt: action.payload };
    case 'SET_STOP_SEQUENCES':
      return { ...state, stopSequences: action.payload };
    case 'RESET_TO_DEFAULTS':
      return { ...defaultSettings };
    case 'LOAD_SETTINGS':
      return { ...state, ...action.payload };
    default:
      return state;
  }
}

describe('settingsReducer', () => {
  let initialState: ModelSettings;

  beforeEach(() => {
    initialState = { ...defaultSettings };
  });

  describe('SET_TEMPERATURE', () => {
    it('updates temperature', () => {
      const result = settingsReducer(initialState, { type: 'SET_TEMPERATURE', payload: 0.7 });
      expect(result.temperature).toBe(0.7);
    });

    it('preserves other settings', () => {
      const result = settingsReducer(initialState, { type: 'SET_TEMPERATURE', payload: 0.5 });
      expect(result.maxOutputTokens).toBe(defaultSettings.maxOutputTokens);
      expect(result.topP).toBe(defaultSettings.topP);
    });

    it('allows 0 temperature', () => {
      const result = settingsReducer(initialState, { type: 'SET_TEMPERATURE', payload: 0 });
      expect(result.temperature).toBe(0);
    });

    it('allows 2.0 temperature', () => {
      const result = settingsReducer(initialState, { type: 'SET_TEMPERATURE', payload: 2.0 });
      expect(result.temperature).toBe(2.0);
    });
  });

  describe('SET_MAX_TOKENS', () => {
    it('updates maxOutputTokens', () => {
      const result = settingsReducer(initialState, { type: 'SET_MAX_TOKENS', payload: 4096 });
      expect(result.maxOutputTokens).toBe(4096);
    });

    it('allows very large values', () => {
      const result = settingsReducer(initialState, { type: 'SET_MAX_TOKENS', payload: 65536 });
      expect(result.maxOutputTokens).toBe(65536);
    });
  });

  describe('SET_TOP_P', () => {
    it('updates topP', () => {
      const result = settingsReducer(initialState, { type: 'SET_TOP_P', payload: 0.8 });
      expect(result.topP).toBe(0.8);
    });

    it('allows 0', () => {
      const result = settingsReducer(initialState, { type: 'SET_TOP_P', payload: 0 });
      expect(result.topP).toBe(0);
    });

    it('allows 1.0', () => {
      const result = settingsReducer(initialState, { type: 'SET_TOP_P', payload: 1.0 });
      expect(result.topP).toBe(1.0);
    });
  });

  describe('SET_THINKING_LEVEL', () => {
    it('updates thinking level', () => {
      const result = settingsReducer(initialState, { type: 'SET_THINKING_LEVEL', payload: 'low' });
      expect(result.thinkingLevel).toBe('low');
    });

    it('accepts string values', () => {
      const result = settingsReducer(initialState, { type: 'SET_THINKING_LEVEL', payload: 'minimal' });
      expect(result.thinkingLevel).toBe('minimal');
    });

    it('accepts all valid levels', () => {
      const levels: ThinkingLevel[] = ['minimal', 'low', 'medium', 'high'];
      levels.forEach(level => {
        const result = settingsReducer(initialState, { type: 'SET_THINKING_LEVEL', payload: level });
        expect(result.thinkingLevel).toBe(level);
      });
    });
  });

  describe('SET_ENABLE_THINKING', () => {
    it('enables thinking', () => {
      const stateWithThinkingOff = { ...initialState, enableThinking: false };
      const result = settingsReducer(stateWithThinkingOff, { type: 'SET_ENABLE_THINKING', payload: true });
      expect(result.enableThinking).toBe(true);
    });

    it('disables thinking', () => {
      const result = settingsReducer(initialState, { type: 'SET_ENABLE_THINKING', payload: false });
      expect(result.enableThinking).toBe(false);
    });
  });

  describe('SET_ENABLE_MANUAL_BUDGET', () => {
    it('enables manual budget', () => {
      const result = settingsReducer(initialState, { type: 'SET_ENABLE_MANUAL_BUDGET', payload: true });
      expect(result.enableManualBudget).toBe(true);
    });

    it('disables manual budget', () => {
      const stateWithBudget = { ...initialState, enableManualBudget: true };
      const result = settingsReducer(stateWithBudget, { type: 'SET_ENABLE_MANUAL_BUDGET', payload: false });
      expect(result.enableManualBudget).toBe(false);
    });
  });

  describe('SET_THINKING_BUDGET', () => {
    it('updates thinking budget', () => {
      const result = settingsReducer(initialState, { type: 'SET_THINKING_BUDGET', payload: 16384 });
      expect(result.thinkingBudget).toBe(16384);
    });

    it('allows 0 budget', () => {
      const result = settingsReducer(initialState, { type: 'SET_THINKING_BUDGET', payload: 0 });
      expect(result.thinkingBudget).toBe(0);
    });

    it('allows large budget values', () => {
      const result = settingsReducer(initialState, { type: 'SET_THINKING_BUDGET', payload: 32768 });
      expect(result.thinkingBudget).toBe(32768);
    });
  });

  describe('SET_ENABLE_GOOGLE_SEARCH', () => {
    it('enables Google Search', () => {
      const result = settingsReducer(initialState, { type: 'SET_ENABLE_GOOGLE_SEARCH', payload: true });
      expect(result.enableGoogleSearch).toBe(true);
    });

    it('disables Google Search', () => {
      const stateWithSearch = { ...initialState, enableGoogleSearch: true };
      const result = settingsReducer(stateWithSearch, { type: 'SET_ENABLE_GOOGLE_SEARCH', payload: false });
      expect(result.enableGoogleSearch).toBe(false);
    });
  });

  describe('SET_SYSTEM_PROMPT', () => {
    it('updates system prompt', () => {
      const prompt = 'You are a helpful assistant.';
      const result = settingsReducer(initialState, { type: 'SET_SYSTEM_PROMPT', payload: prompt });
      expect(result.systemPrompt).toBe(prompt);
    });

    it('allows empty prompt', () => {
      const stateWithPrompt = { ...initialState, systemPrompt: 'Some prompt' };
      const result = settingsReducer(stateWithPrompt, { type: 'SET_SYSTEM_PROMPT', payload: '' });
      expect(result.systemPrompt).toBe('');
    });

    it('handles unicode characters', () => {
      const unicodePrompt = '你是一个有帮助的助手。🤖';
      const result = settingsReducer(initialState, { type: 'SET_SYSTEM_PROMPT', payload: unicodePrompt });
      expect(result.systemPrompt).toBe(unicodePrompt);
    });
  });

  describe('SET_STOP_SEQUENCES', () => {
    it('updates stop sequences', () => {
      const sequences = ['###', '---', '\n\n'];
      const result = settingsReducer(initialState, { type: 'SET_STOP_SEQUENCES', payload: sequences });
      expect(result.stopSequences).toEqual(sequences);
    });

    it('allows empty array', () => {
      const stateWithSequences = { ...initialState, stopSequences: ['###'] };
      const result = settingsReducer(stateWithSequences, { type: 'SET_STOP_SEQUENCES', payload: [] });
      expect(result.stopSequences).toEqual([]);
    });
  });

  describe('RESET_TO_DEFAULTS', () => {
    it('resets all settings to defaults', () => {
      const modifiedState: ModelSettings = {
        temperature: 0.5,
        maxOutputTokens: 2048,
        topP: 0.5,
        thinkingLevel: 'low',
        enableThinking: false,
        enableManualBudget: true,
        thinkingBudget: 4096,
        enableGoogleSearch: true,
        systemPrompt: 'Custom prompt',
        stopSequences: ['###'],
      };

      const result = settingsReducer(modifiedState, { type: 'RESET_TO_DEFAULTS' });
      
      expect(result.temperature).toBe(defaultSettings.temperature);
      expect(result.maxOutputTokens).toBe(defaultSettings.maxOutputTokens);
      expect(result.topP).toBe(defaultSettings.topP);
      expect(result.thinkingLevel).toBe(defaultSettings.thinkingLevel);
      expect(result.enableThinking).toBe(defaultSettings.enableThinking);
      expect(result.enableManualBudget).toBe(defaultSettings.enableManualBudget);
      expect(result.thinkingBudget).toBe(defaultSettings.thinkingBudget);
      expect(result.enableGoogleSearch).toBe(defaultSettings.enableGoogleSearch);
    });
  });

  describe('LOAD_SETTINGS', () => {
    it('merges partial settings', () => {
      const result = settingsReducer(initialState, {
        type: 'LOAD_SETTINGS',
        payload: { temperature: 0.8, topP: 0.9 },
      });

      expect(result.temperature).toBe(0.8);
      expect(result.topP).toBe(0.9);
      expect(result.maxOutputTokens).toBe(defaultSettings.maxOutputTokens);
    });

    it('preserves unloaded settings', () => {
      const result = settingsReducer(initialState, {
        type: 'LOAD_SETTINGS',
        payload: { enableGoogleSearch: true },
      });

      expect(result.enableGoogleSearch).toBe(true);
      expect(result.temperature).toBe(defaultSettings.temperature);
      expect(result.systemPrompt).toBe(defaultSettings.systemPrompt);
    });

    it('handles empty payload', () => {
      const result = settingsReducer(initialState, {
        type: 'LOAD_SETTINGS',
        payload: {},
      });

      expect(result).toEqual(initialState);
    });
  });

  describe('Unknown action', () => {
    it('returns current state for unknown action', () => {
      // @ts-expect-error Testing unknown action type
      const result = settingsReducer(initialState, { type: 'UNKNOWN_ACTION' });
      expect(result).toEqual(initialState);
    });
  });

  describe('Immutability', () => {
    it('does not mutate original state', () => {
      const originalState = { ...initialState };
      const frozen = Object.freeze(originalState);
      
      // This would throw if we tried to mutate frozen object
      const result = settingsReducer(frozen as ModelSettings, { type: 'SET_TEMPERATURE', payload: 0.5 });
      
      expect(result).not.toBe(frozen);
      expect(result.temperature).toBe(0.5);
      expect(frozen.temperature).toBe(initialState.temperature);
    });
  });
});
