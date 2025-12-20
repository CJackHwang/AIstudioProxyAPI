/**
 * useModelCapabilities Hook Tests
 * 
 * Tests the pattern matching and capability lookup logic
 */

import { describe, it, expect } from 'vitest';

// Since the hook uses React Query, we test the pure logic separately
// by extracting and testing the matching algorithm

// Simulate the backend response structure
interface MockCapabilitiesResponse {
  categories: Record<string, {
    thinkingType: 'level' | 'budget' | 'none';
    levels?: string[];
    defaultLevel?: string;
    alwaysOn?: boolean;
    budgetRange?: [number, number];
    defaultBudget?: number;
    supportsGoogleSearch?: boolean;
  }>;
  matchers: Array<{ pattern: string; category: string }>;
}

// Mock backend response (matching actual backend implementation)
const mockCapabilitiesData: MockCapabilitiesResponse = {
  categories: {
    gemini3Flash: {
      thinkingType: 'level',
      levels: ['minimal', 'low', 'medium', 'high'],
      defaultLevel: 'medium',
      alwaysOn: true,
      supportsGoogleSearch: true,
    },
    gemini3Pro: {
      thinkingType: 'level',
      levels: ['low', 'high'],
      defaultLevel: 'high',
      alwaysOn: true,
      supportsGoogleSearch: true,
    },
    gemini25Pro: {
      thinkingType: 'budget',
      budgetRange: [128, 32768],
      defaultBudget: 8192,
      supportsGoogleSearch: true,
    },
    gemini25Flash: {
      thinkingType: 'budget',
      budgetRange: [0, 24576],
      defaultBudget: 8192,
      supportsGoogleSearch: true,
    },
    gemini2: {
      thinkingType: 'none',
      supportsGoogleSearch: false,
    },
    other: {
      thinkingType: 'none',
      supportsGoogleSearch: true,
    },
  },
  matchers: [
    { pattern: 'gemini-3.*flash|gemini3.*flash', category: 'gemini3Flash' },
    { pattern: 'gemini-3.*pro|gemini3.*pro', category: 'gemini3Pro' },
    { pattern: 'gemini-2\\.5.*pro|gemini-2\\.5pro', category: 'gemini25Pro' },
    { pattern: 'gemini-2\\.5.*flash|gemini-flash-latest|gemini-flash-lite-latest', category: 'gemini25Flash' },
    { pattern: 'gemini-2\\.0|gemini2\\.0', category: 'gemini2' },
  ],
};

/**
 * Pure function matching logic (extracted from the hook)
 */
function getModelCategory(modelId: string, matchers: MockCapabilitiesResponse['matchers']): string {
  const modelLower = modelId.toLowerCase();
  
  for (const matcher of matchers) {
    const regex = new RegExp(matcher.pattern, 'i');
    if (regex.test(modelLower)) {
      return matcher.category;
    }
  }
  
  return 'other';
}

function getModelCapabilities(modelId: string, data: MockCapabilitiesResponse) {
  const category = getModelCategory(modelId, data.matchers);
  return data.categories[category];
}

describe('Model Category Pattern Matching', () => {
  describe('Gemini 3 Flash models', () => {
    it('matches gemini-3-flash', () => {
      expect(getModelCategory('gemini-3-flash', mockCapabilitiesData.matchers)).toBe('gemini3Flash');
    });

    it('matches gemini-3.0-flash', () => {
      expect(getModelCategory('gemini-3.0-flash', mockCapabilitiesData.matchers)).toBe('gemini3Flash');
    });

    it('matches gemini-3-flash-thinking', () => {
      expect(getModelCategory('gemini-3-flash-thinking', mockCapabilitiesData.matchers)).toBe('gemini3Flash');
    });

    it('matches case insensitively', () => {
      expect(getModelCategory('GEMINI-3-FLASH', mockCapabilitiesData.matchers)).toBe('gemini3Flash');
    });
  });

  describe('Gemini 3 Pro models', () => {
    it('matches gemini-3-pro', () => {
      expect(getModelCategory('gemini-3-pro', mockCapabilitiesData.matchers)).toBe('gemini3Pro');
    });

    it('matches gemini-3.0-pro', () => {
      expect(getModelCategory('gemini-3.0-pro', mockCapabilitiesData.matchers)).toBe('gemini3Pro');
    });
  });

  describe('Gemini 2.5 Pro models', () => {
    it('matches gemini-2.5-pro', () => {
      expect(getModelCategory('gemini-2.5-pro', mockCapabilitiesData.matchers)).toBe('gemini25Pro');
    });

    it('matches gemini-2.5-pro-latest', () => {
      expect(getModelCategory('gemini-2.5-pro-latest', mockCapabilitiesData.matchers)).toBe('gemini25Pro');
    });

    it('matches gemini-2.5-pro-preview-0506', () => {
      expect(getModelCategory('gemini-2.5-pro-preview-0506', mockCapabilitiesData.matchers)).toBe('gemini25Pro');
    });
  });

  describe('Gemini 2.5 Flash models', () => {
    it('matches gemini-2.5-flash', () => {
      expect(getModelCategory('gemini-2.5-flash', mockCapabilitiesData.matchers)).toBe('gemini25Flash');
    });

    it('matches gemini-2.5-flash-lite', () => {
      expect(getModelCategory('gemini-2.5-flash-lite', mockCapabilitiesData.matchers)).toBe('gemini25Flash');
    });

    it('matches gemini-flash-latest alias', () => {
      expect(getModelCategory('gemini-flash-latest', mockCapabilitiesData.matchers)).toBe('gemini25Flash');
    });

    it('matches gemini-flash-lite-latest alias', () => {
      expect(getModelCategory('gemini-flash-lite-latest', mockCapabilitiesData.matchers)).toBe('gemini25Flash');
    });
  });

  describe('Gemini 2.0 models (no thinking)', () => {
    it('matches gemini-2.0-flash', () => {
      expect(getModelCategory('gemini-2.0-flash', mockCapabilitiesData.matchers)).toBe('gemini2');
    });

    it('matches gemini-2.0-flash-lite', () => {
      expect(getModelCategory('gemini-2.0-flash-lite', mockCapabilitiesData.matchers)).toBe('gemini2');
    });
  });

  describe('Unknown models', () => {
    it('returns other for gpt-4', () => {
      expect(getModelCategory('gpt-4', mockCapabilitiesData.matchers)).toBe('other');
    });

    it('returns other for empty string', () => {
      expect(getModelCategory('', mockCapabilitiesData.matchers)).toBe('other');
    });

    it('returns other for claude-3-opus', () => {
      expect(getModelCategory('claude-3-opus', mockCapabilitiesData.matchers)).toBe('other');
    });
  });
});

describe('Model Capabilities Lookup', () => {
  describe('Thinking type detection', () => {
    it('gemini3Flash uses level selector', () => {
      const caps = getModelCapabilities('gemini-3-flash', mockCapabilitiesData);
      expect(caps.thinkingType).toBe('level');
      expect(caps.levels).toEqual(['minimal', 'low', 'medium', 'high']);
    });

    it('gemini25Pro uses budget slider', () => {
      const caps = getModelCapabilities('gemini-2.5-pro', mockCapabilitiesData);
      expect(caps.thinkingType).toBe('budget');
      expect(caps.budgetRange).toEqual([128, 32768]);
    });

    it('gemini2 has no thinking', () => {
      const caps = getModelCapabilities('gemini-2.0-flash', mockCapabilitiesData);
      expect(caps.thinkingType).toBe('none');
    });
  });

  describe('Always-on thinking detection', () => {
    it('gemini3Flash has always-on thinking', () => {
      const caps = getModelCapabilities('gemini-3-flash', mockCapabilitiesData);
      expect(caps.alwaysOn).toBe(true);
    });

    it('gemini25Pro does not have always-on', () => {
      const caps = getModelCapabilities('gemini-2.5-pro', mockCapabilitiesData);
      expect(caps.alwaysOn).toBeUndefined();
    });
  });

  describe('Google Search support', () => {
    it('gemini3Flash supports Google Search', () => {
      const caps = getModelCapabilities('gemini-3-flash', mockCapabilitiesData);
      expect(caps.supportsGoogleSearch).toBe(true);
    });

    it('gemini2 does not support Google Search', () => {
      const caps = getModelCapabilities('gemini-2.0-flash', mockCapabilitiesData);
      expect(caps.supportsGoogleSearch).toBe(false);
    });
  });

  describe('Default values', () => {
    it('gemini3Flash has default level "medium"', () => {
      const caps = getModelCapabilities('gemini-3-flash', mockCapabilitiesData);
      expect(caps.defaultLevel).toBe('medium');
    });

    it('gemini25Flash has default budget 8192', () => {
      const caps = getModelCapabilities('gemini-2.5-flash', mockCapabilitiesData);
      expect(caps.defaultBudget).toBe(8192);
    });
  });
});

describe('Edge Cases', () => {
  it('handles model ID with special characters', () => {
    // Should fall through to 'other' if no match
    expect(getModelCategory('gemini@3.0-flash!!!', mockCapabilitiesData.matchers)).toBe('other');
  });

  it('prioritizes first matching pattern', () => {
    // "gemini-3-flash-pro" could match both flash and pro patterns
    // The order in matchers determines priority (flash comes first)
    const result = getModelCategory('gemini-3-flash-pro', mockCapabilitiesData.matchers);
    expect(result).toBe('gemini3Flash');
  });

  it('handles very long model IDs', () => {
    const longModelId = 'gemini-2.5-pro-preview-0506-experimental-thinking-enhanced-v2';
    expect(getModelCategory(longModelId, mockCapabilitiesData.matchers)).toBe('gemini25Pro');
  });
});
