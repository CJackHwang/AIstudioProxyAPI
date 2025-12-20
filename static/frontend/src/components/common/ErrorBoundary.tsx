/**
 * Error Boundary Component
 * Catches React errors and displays fallback UI
 */

import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  name?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error(`[ErrorBoundary${this.props.name ? `: ${this.props.name}` : ''}]`, error, errorInfo);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div style={{
          padding: '1rem',
          margin: '1rem',
          borderRadius: '0.5rem',
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          color: '#ef4444',
        }}>
          <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '0.9rem' }}>
            {this.props.name || '组件'} 加载失败
          </h3>
          <p style={{ margin: 0, fontSize: '0.8rem', opacity: 0.8 }}>
            {this.state.error?.message || '未知错误'}
          </p>
          <button 
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              marginTop: '0.5rem',
              padding: '0.25rem 0.5rem',
              fontSize: '0.75rem',
              borderRadius: '0.25rem',
              backgroundColor: 'rgba(239, 68, 68, 0.2)',
              color: '#ef4444',
              border: 'none',
              cursor: 'pointer',
            }}
          >
            重试
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
