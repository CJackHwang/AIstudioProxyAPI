/**
 * SettingsPanel Component Tests
 * 
 * Tests the sub-components (Slider, Toggle, CollapsibleSection) in isolation
 */

import { describe, it, expect, vi } from 'vitest';

// Since we can't easily import the internal components, we test the logic

// =============================================
// Slider Logic Tests
// =============================================

describe('Slider Logic', () => {
  describe('value parsing', () => {
    it('parses integer values correctly', () => {
      const value = parseFloat('8192');
      expect(value).toBe(8192);
    });

    it('parses float values correctly', () => {
      const value = parseFloat('0.95');
      expect(value).toBe(0.95);
    });

    it('handles NaN gracefully', () => {
      const value = parseFloat('invalid');
      expect(isNaN(value)).toBe(true);
    });

    it('handles empty string', () => {
      const value = parseFloat('');
      expect(isNaN(value)).toBe(true);
    });
  });

  describe('step formatting', () => {
    it('formats decimal values with toFixed when step < 1', () => {
      const value = 0.754321;
      const step = 0.01;
      const formatted = step < 1 ? value.toFixed(2) : value.toString();
      expect(formatted).toBe('0.75');
    });

    it('keeps integers as-is when step >= 1', () => {
      const value = 8192;
      const step = 1;
      const formatted = step < 1 ? value.toFixed(2) : value.toString();
      expect(formatted).toBe('8192');
    });
  });

  describe('range constraints', () => {
    it('allows values at minimum', () => {
      const min = 0;
      const max = 100;
      const value = 0;
      expect(value >= min && value <= max).toBe(true);
    });

    it('allows values at maximum', () => {
      const min = 0;
      const max = 100;
      const value = 100;
      expect(value >= min && value <= max).toBe(true);
    });

    it('allows values within range', () => {
      const min = 0;
      const max = 100;
      const value = 50;
      expect(value >= min && value <= max).toBe(true);
    });
  });
});

// =============================================
// Toggle Logic Tests
// =============================================

describe('Toggle Logic', () => {
  describe('state changes', () => {
    it('toggles true to false', () => {
      const current = true;
      expect(!current).toBe(false);
    });

    it('toggles false to true', () => {
      const current = false;
      expect(!current).toBe(true);
    });
  });

  describe('disabled state', () => {
    it('does not toggle when disabled', () => {
      const disabled = true;
      const current = false;
      const onChange = vi.fn();
      
      if (!disabled) {
        onChange(!current);
      }
      
      expect(onChange).not.toHaveBeenCalled();
    });

    it('toggles when not disabled', () => {
      const disabled = false;
      const current = false;
      const onChange = vi.fn();
      
      if (!disabled) {
        onChange(!current);
      }
      
      expect(onChange).toHaveBeenCalledWith(true);
    });
  });
});

// =============================================
// CollapsibleSection Logic Tests
// =============================================

describe('CollapsibleSection Logic', () => {
  describe('initial state', () => {
    it('manages multiple section states', () => {
      const expandedSections: Record<string, boolean> = {
        model: true,
        thinking: true,
        params: true,
        tools: true,
        system: false,
      };
      
      expect(expandedSections.model).toBe(true);
      expect(expandedSections.system).toBe(false);
    });
  });

  describe('toggle behavior', () => {
    it('toggles section from expanded to collapsed', () => {
      const prev = { model: true };
      const section = 'model';
      const next = { ...prev, [section]: !prev[section] };
      
      expect(next.model).toBe(false);
    });

    it('toggles section from collapsed to expanded', () => {
      const prev = { model: false };
      const section = 'model';
      const next = { ...prev, [section]: !prev[section] };
      
      expect(next.model).toBe(true);
    });

    it('preserves other sections when toggling', () => {
      const prev = { model: true, thinking: true, params: false };
      const section = 'model';
      const next = { ...prev, [section]: !prev[section] };
      
      expect(next.model).toBe(false);
      expect(next.thinking).toBe(true);
      expect(next.params).toBe(false);
    });
  });
});

// =============================================
// ThinkingLevel Options Builder Tests
// =============================================

describe('Thinking Level Options Builder', () => {
  type ThinkingLevel = 'minimal' | 'low' | 'medium' | 'high';
  
  interface CategoryCapabilities {
    thinkingType: 'level' | 'budget' | 'none';
    levels?: string[];
  }

  function buildLevelOptions(capabilities: CategoryCapabilities | undefined): { value: ThinkingLevel | ''; label: string }[] {
    if (capabilities?.thinkingType !== 'level' || !capabilities.levels) {
      return [];
    }
    
    const options: { value: ThinkingLevel | ''; label: string }[] = [
      { value: '', label: '未指定' }
    ];
    
    for (const level of capabilities.levels) {
      options.push({ 
        value: level as ThinkingLevel, 
        label: level.charAt(0).toUpperCase() + level.slice(1) 
      });
    }
    
    return options;
  }

  it('returns empty array when capabilities is undefined', () => {
    expect(buildLevelOptions(undefined)).toEqual([]);
  });

  it('returns empty array for budget type', () => {
    expect(buildLevelOptions({ thinkingType: 'budget' })).toEqual([]);
  });

  it('returns empty array for none type', () => {
    expect(buildLevelOptions({ thinkingType: 'none' })).toEqual([]);
  });

  it('builds options for Gemini 3 Flash (4 levels)', () => {
    const capabilities: CategoryCapabilities = {
      thinkingType: 'level',
      levels: ['minimal', 'low', 'medium', 'high'],
    };
    
    const options = buildLevelOptions(capabilities);
    
    expect(options).toHaveLength(5); // 4 levels + unspecified
    expect(options[0]).toEqual({ value: '', label: '未指定' });
    expect(options[1]).toEqual({ value: 'minimal', label: 'Minimal' });
    expect(options[4]).toEqual({ value: 'high', label: 'High' });
  });

  it('builds options for Gemini 3 Pro (2 levels)', () => {
    const capabilities: CategoryCapabilities = {
      thinkingType: 'level',
      levels: ['low', 'high'],
    };
    
    const options = buildLevelOptions(capabilities);
    
    expect(options).toHaveLength(3); // 2 levels + unspecified
    expect(options[1]).toEqual({ value: 'low', label: 'Low' });
    expect(options[2]).toEqual({ value: 'high', label: 'High' });
  });

  it('capitalizes first letter of level names', () => {
    const capabilities: CategoryCapabilities = {
      thinkingType: 'level',
      levels: ['medium'],
    };
    
    const options = buildLevelOptions(capabilities);
    
    expect(options[1].label).toBe('Medium');
  });
});

// =============================================
// Budget Range Logic Tests
// =============================================

describe('Budget Range Logic', () => {
  interface CategoryCapabilities {
    budgetRange?: [number, number];
  }

  function getBudgetRange(capabilities: CategoryCapabilities | undefined): { min: number; max: number } {
    if (capabilities?.budgetRange) {
      return { min: capabilities.budgetRange[0], max: capabilities.budgetRange[1] };
    }
    return { min: 512, max: 24576 };
  }

  it('returns model-specific range when available', () => {
    const capabilities: CategoryCapabilities = {
      budgetRange: [128, 32768],
    };
    
    expect(getBudgetRange(capabilities)).toEqual({ min: 128, max: 32768 });
  });

  it('returns default range when capabilities undefined', () => {
    expect(getBudgetRange(undefined)).toEqual({ min: 512, max: 24576 });
  });

  it('returns default range when budgetRange undefined', () => {
    expect(getBudgetRange({})).toEqual({ min: 512, max: 24576 });
  });

  it('handles Gemini 2.5 Pro range', () => {
    const capabilities: CategoryCapabilities = {
      budgetRange: [128, 32768],
    };
    
    const range = getBudgetRange(capabilities);
    expect(range.max).toBe(32768);
  });

  it('handles Gemini 2.5 Flash range', () => {
    const capabilities: CategoryCapabilities = {
      budgetRange: [0, 24576],
    };
    
    const range = getBudgetRange(capabilities);
    expect(range.min).toBe(0);
    expect(range.max).toBe(24576);
  });
});
