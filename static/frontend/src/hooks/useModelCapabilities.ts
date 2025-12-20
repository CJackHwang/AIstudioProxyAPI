/**
 * Model Capabilities Hook
 * Fetches model capabilities from backend single source of truth
 */

import { useQuery } from '@tanstack/react-query';

// Types matching backend response
export type ThinkingType = 'level' | 'budget' | 'none';

export interface CategoryCapabilities {
  thinkingType: ThinkingType;
  levels?: string[];
  defaultLevel?: string;
  alwaysOn?: boolean;
  budgetRange?: [number, number];
  defaultBudget?: number;
  supportsGoogleSearch?: boolean;
}

export interface ModelCapabilitiesResponse {
  categories: Record<string, CategoryCapabilities>;
  matchers: Array<{ pattern: string; category: string }>;
}

export type ModelCategory = 
  | 'gemini3Flash'
  | 'gemini3Pro'
  | 'gemini25Pro'
  | 'gemini25Flash'
  | 'gemini2'
  | 'other';

async function fetchCapabilities(): Promise<ModelCapabilitiesResponse> {
  const response = await fetch('/api/model-capabilities');
  if (!response.ok) {
    throw new Error('Failed to fetch model capabilities');
  }
  return response.json();
}

/**
 * Hook to fetch and cache model capabilities
 * Returns capabilities and helper functions
 */
export function useModelCapabilities() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['model-capabilities'],
    queryFn: fetchCapabilities,
    staleTime: Infinity, // Capabilities rarely change
    gcTime: Infinity,
  });

  /**
   * Get category for a model ID using backend-provided matchers
   */
  const getModelCategory = (modelId: string): ModelCategory => {
    if (!data) return 'other';
    
    const modelLower = modelId.toLowerCase();
    
    for (const matcher of data.matchers) {
      const regex = new RegExp(matcher.pattern, 'i');
      if (regex.test(modelLower)) {
        return matcher.category as ModelCategory;
      }
    }
    
    return 'other';
  };

  /**
   * Get capabilities for a specific category
   */
  const getCategoryCapabilities = (category: ModelCategory): CategoryCapabilities | undefined => {
    return data?.categories[category];
  };

  /**
   * Get capabilities for a model ID
   */
  const getModelCapabilities = (modelId: string): CategoryCapabilities | undefined => {
    const category = getModelCategory(modelId);
    return getCategoryCapabilities(category);
  };

  return {
    data,
    isLoading,
    error,
    getModelCategory,
    getCategoryCapabilities,
    getModelCapabilities,
  };
}
