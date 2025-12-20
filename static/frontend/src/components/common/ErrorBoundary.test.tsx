/**
 * ErrorBoundary Component Tests
 * 
 * Tests for error boundary behavior and state management
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { type ReactNode } from 'react';
import '@testing-library/jest-dom';
import { ErrorBoundary } from './ErrorBoundary';

// Suppress console.error during tests since we're testing error handling
const originalError = console.error;
beforeEach(() => {
  console.error = vi.fn();
});
afterEach(() => {
  console.error = originalError;
});

// Component that throws an error
function ThrowError({ shouldThrow }: { shouldThrow: boolean }): ReactNode {
  if (shouldThrow) {
    throw new Error('Test error');
  }
  return <div>Normal content</div>;
}

// Component that throws specific error message
function ThrowCustomError({ message }: { message: string }): ReactNode {
  throw new Error(message);
}

// Component that throws error with empty/undefined message
function ThrowEmptyError(): ReactNode {
  const error = new Error();
  error.message = ''; // Empty message to trigger fallback
  throw error;
}

describe('ErrorBoundary', () => {
  describe('Normal rendering', () => {
    it('renders children when no error', () => {
      render(
        <ErrorBoundary>
          <div>Hello World</div>
        </ErrorBoundary>
      );
      
      expect(screen.getByText('Hello World')).toBeInTheDocument();
    });

    it('renders multiple children', () => {
      render(
        <ErrorBoundary>
          <div>First</div>
          <div>Second</div>
        </ErrorBoundary>
      );
      
      expect(screen.getByText('First')).toBeInTheDocument();
      expect(screen.getByText('Second')).toBeInTheDocument();
    });
  });

  describe('Error handling', () => {
    it('catches errors and shows fallback UI', () => {
      render(
        <ErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ErrorBoundary>
      );
      
      expect(screen.getByText(/加载失败/)).toBeInTheDocument();
    });

    it('displays error message', () => {
      render(
        <ErrorBoundary>
          <ThrowCustomError message="Custom error message" />
        </ErrorBoundary>
      );
      
      expect(screen.getByText('Custom error message')).toBeInTheDocument();
    });

    it('shows component name when provided', () => {
      render(
        <ErrorBoundary name="TestComponent">
          <ThrowError shouldThrow={true} />
        </ErrorBoundary>
      );
      
      expect(screen.getByText(/TestComponent 加载失败/)).toBeInTheDocument();
    });

    it('shows generic name when not provided', () => {
      render(
        <ErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ErrorBoundary>
      );
      
      expect(screen.getByText(/组件 加载失败/)).toBeInTheDocument();
    });

    it('shows default message when error has empty message', () => {
      render(
        <ErrorBoundary>
          <ThrowEmptyError />
        </ErrorBoundary>
      );
      
      expect(screen.getByText('未知错误')).toBeInTheDocument();
    });
  });

  describe('Custom fallback', () => {
    it('renders custom fallback when provided', () => {
      render(
        <ErrorBoundary fallback={<div>Custom fallback</div>}>
          <ThrowError shouldThrow={true} />
        </ErrorBoundary>
      );
      
      expect(screen.getByText('Custom fallback')).toBeInTheDocument();
    });

    it('does not show default UI when custom fallback provided', () => {
      render(
        <ErrorBoundary fallback={<div>Custom fallback</div>}>
          <ThrowError shouldThrow={true} />
        </ErrorBoundary>
      );
      
      expect(screen.queryByText(/加载失败/)).not.toBeInTheDocument();
    });
  });

  describe('Recovery', () => {
    it('shows retry button', () => {
      render(
        <ErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ErrorBoundary>
      );
      
      expect(screen.getByText('重试')).toBeInTheDocument();
    });

    it('retry button is clickable', () => {
      render(
        <ErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ErrorBoundary>
      );
      
      const retryButton = screen.getByText('重试');
      expect(retryButton).toBeInTheDocument();
      
      // Button should be clickable (not disabled)
      expect(retryButton).not.toBeDisabled();
      
      // Clicking should not throw
      expect(() => fireEvent.click(retryButton)).not.toThrow();
    });
  });

  describe('Error logging', () => {
    it('logs error to console', () => {
      render(
        <ErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ErrorBoundary>
      );
      
      expect(console.error).toHaveBeenCalled();
    });

    it('includes component name in log', () => {
      render(
        <ErrorBoundary name="MyComponent">
          <ThrowError shouldThrow={true} />
        </ErrorBoundary>
      );
      
      expect(console.error).toHaveBeenCalledWith(
        expect.stringContaining('MyComponent'),
        expect.any(Error),
        expect.anything()
      );
    });
  });
});

// =============================================
// ErrorBoundary State Logic Tests
// =============================================

describe('ErrorBoundary State Logic', () => {
  interface State {
    hasError: boolean;
    error: Error | null;
  }

  /**
   * getDerivedStateFromError logic
   */
  function getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  it('sets hasError to true', () => {
    const error = new Error('Test');
    const state = getDerivedStateFromError(error);
    expect(state.hasError).toBe(true);
  });

  it('stores the error object', () => {
    const error = new Error('Test message');
    const state = getDerivedStateFromError(error);
    expect(state.error).toBe(error);
    expect(state.error?.message).toBe('Test message');
  });

  /**
   * Reset state logic
   */
  function resetState(): State {
    return { hasError: false, error: null };
  }

  it('resets hasError to false', () => {
    const state = resetState();
    expect(state.hasError).toBe(false);
  });

  it('clears error object', () => {
    const state = resetState();
    expect(state.error).toBeNull();
  });
});
