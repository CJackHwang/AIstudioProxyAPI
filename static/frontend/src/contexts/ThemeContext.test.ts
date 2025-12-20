/**
 * Theme Context Tests
 * 
 * Tests the theme toggle logic
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock localStorage and matchMedia
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
    clear: () => { store = {}; },
    removeItem: vi.fn((key: string) => { delete store[key]; }),
  };
})();

vi.stubGlobal('localStorage', localStorageMock);

// Theme toggle logic extracted from ThemeContext
type Theme = 'light' | 'dark';

function getInitialTheme(prefersDark: boolean): Theme {
  const stored = localStorage.getItem('theme') as Theme | null;
  if (stored === 'light' || stored === 'dark') return stored;
  return prefersDark ? 'dark' : 'light';
}

function toggleTheme(current: Theme): Theme {
  return current === 'dark' ? 'light' : 'dark';
}

describe('Theme Logic', () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.clearAllMocks();
  });

  describe('getInitialTheme', () => {
    it('returns stored light theme', () => {
      localStorage.setItem('theme', 'light');
      expect(getInitialTheme(true)).toBe('light');
    });

    it('returns stored dark theme', () => {
      localStorage.setItem('theme', 'dark');
      expect(getInitialTheme(false)).toBe('dark');
    });

    it('respects system preference for dark when no stored theme', () => {
      expect(getInitialTheme(true)).toBe('dark');
    });

    it('respects system preference for light when no stored theme', () => {
      expect(getInitialTheme(false)).toBe('light');
    });

    it('ignores invalid stored values', () => {
      localStorage.setItem('theme', 'invalid');
      expect(getInitialTheme(true)).toBe('dark');
    });

    it('handles null localStorage', () => {
      // localStorage.getItem returns null by default
      expect(getInitialTheme(false)).toBe('light');
    });
  });

  describe('toggleTheme', () => {
    it('toggles from dark to light', () => {
      expect(toggleTheme('dark')).toBe('light');
    });

    it('toggles from light to dark', () => {
      expect(toggleTheme('light')).toBe('dark');
    });

    it('toggle is reversible', () => {
      const initial: Theme = 'dark';
      const toggled = toggleTheme(initial);
      const toggledBack = toggleTheme(toggled);
      
      expect(toggledBack).toBe(initial);
    });
  });

  describe('Theme Persistence', () => {
    it('stores theme changes', () => {
      localStorage.setItem('theme', 'dark');
      expect(localStorage.getItem('theme')).toBe('dark');
      
      localStorage.setItem('theme', 'light');
      expect(localStorage.getItem('theme')).toBe('light');
    });

    it('persists across getInitialTheme calls', () => {
      localStorage.setItem('theme', 'light');
      expect(getInitialTheme(true)).toBe('light');
      expect(getInitialTheme(false)).toBe('light');
    });
  });
});

describe('Theme Integration', () => {
  beforeEach(() => {
    localStorageMock.clear();
  });

  it('simulates full theme toggle flow', () => {
    // Start with no preference, system prefers dark
    let currentTheme = getInitialTheme(true);
    expect(currentTheme).toBe('dark');

    // Toggle to light
    currentTheme = toggleTheme(currentTheme);
    localStorage.setItem('theme', currentTheme);
    expect(currentTheme).toBe('light');

    // Simulate page reload - should persist
    currentTheme = getInitialTheme(true);
    expect(currentTheme).toBe('light');

    // Toggle back to dark
    currentTheme = toggleTheme(currentTheme);
    localStorage.setItem('theme', currentTheme);
    expect(currentTheme).toBe('dark');
  });

  it('handles theme cycle correctly', () => {
    let theme: Theme = 'light';
    
    for (let i = 0; i < 10; i++) {
      theme = toggleTheme(theme);
      expect(['light', 'dark']).toContain(theme);
    }
    
    // After 10 toggles from light, should be back to light (even number)
    expect(theme).toBe('light');
  });
});
