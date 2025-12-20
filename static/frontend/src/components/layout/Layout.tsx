/**
 * Layout Component
 * Main application layout with tabbed sidebars and error boundaries
 */

import { useState } from 'react';
import { 
  PanelLeft, 
  PanelRight, 
  Moon, 
  Sun,
  Layers,
  Settings,
  MessageSquare
} from 'lucide-react';
import { useTheme } from '@/contexts';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { ChatPanel } from '@/components/chat/ChatPanel';
import { SettingsPanel } from '@/components/settings/SettingsPanel';
import { SettingsPage } from '@/components/settings/SettingsPage';
import { LogViewer } from '@/components/logs/LogViewer';
import styles from './Layout.module.css';

type MainView = 'chat' | 'settings';

export function Layout() {
  const { theme, toggleTheme } = useTheme();
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(true);
  const [rightSidebarOpen, setRightSidebarOpen] = useState(true);
  const [mainView, setMainView] = useState<MainView>('chat');

  return (
    <div className={styles.layout}>
      {/* Left Sidebar - Model Settings (only visible in chat mode) */}
      {mainView === 'chat' && (
        <aside 
          className={`${styles.sidebar} ${!leftSidebarOpen ? styles.collapsed : ''}`}
          role="complementary"
          aria-label="模型面板"
        >
          <div className={styles.sidebarHeader}>
            <span className={styles.sidebarTitle}>模型设置</span>
          </div>
          <div className={styles.sidebarContent}>
            <ErrorBoundary name="模型面板">
              <SettingsPanel />
            </ErrorBoundary>
          </div>
        </aside>
      )}

      {/* Main Content */}
      <main className={styles.main} role="main">
        {/* Header */}
        <header className={styles.header} role="banner">
          <div className={styles.headerLeft}>
            {mainView === 'chat' && (
              <button 
                className={styles.toggleButton}
                onClick={() => setLeftSidebarOpen(!leftSidebarOpen)}
                aria-label={leftSidebarOpen ? '隐藏设置面板' : '显示设置面板'}
                aria-expanded={leftSidebarOpen}
              >
                <PanelLeft size={20} aria-hidden="true" />
              </button>
            )}
            <div className={styles.logo}>
              <Layers className={styles.logoIcon} size={24} aria-hidden="true" />
              <span className={styles.logoText}>AI Studio Proxy</span>
            </div>
          </div>
          <div className={styles.headerCenter}>
            <div className={styles.mainTabs}>
              <button
                className={`${styles.mainTab} ${mainView === 'chat' ? styles.active : ''}`}
                onClick={() => setMainView('chat')}
              >
                <MessageSquare size={16} />
                聊天
              </button>
              <button
                className={`${styles.mainTab} ${mainView === 'settings' ? styles.active : ''}`}
                onClick={() => setMainView('settings')}
              >
                <Settings size={16} />
                设置
              </button>
            </div>
          </div>
          <div className={styles.headerRight}>
            <button 
              className={styles.toggleButton}
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? '切换到亮色模式' : '切换到暗色模式'}
            >
              {theme === 'dark' ? <Sun size={20} aria-hidden="true" /> : <Moon size={20} aria-hidden="true" />}
            </button>
            {mainView === 'chat' && (
              <button 
                className={styles.toggleButton}
                onClick={() => setRightSidebarOpen(!rightSidebarOpen)}
                aria-label={rightSidebarOpen ? '隐藏日志面板' : '显示日志面板'}
                aria-expanded={rightSidebarOpen}
              >
                <PanelRight size={20} aria-hidden="true" />
              </button>
            )}
          </div>
        </header>

        {/* Content Area */}
        <div className={styles.content}>
          {mainView === 'chat' ? (
            <div className={styles.chatArea}>
              <ErrorBoundary name="聊天面板">
                <ChatPanel />
              </ErrorBoundary>
            </div>
          ) : (
            <div className={styles.settingsArea}>
              <ErrorBoundary name="设置页面">
                <SettingsPage />
              </ErrorBoundary>
            </div>
          )}
        </div>
      </main>

      {/* Right Sidebar - Logs (only visible in chat mode) */}
      {mainView === 'chat' && (
        <aside 
          className={`${styles.rightSidebar} ${!rightSidebarOpen ? styles.collapsed : ''}`}
          role="complementary"
          aria-label="日志面板"
        >
          <div className={styles.sidebarHeader}>
            <span className={styles.sidebarTitle}>
              日志
            </span>
          </div>
          <div className={styles.sidebarContent}>
            <ErrorBoundary name="日志查看器">
              {rightSidebarOpen && <LogViewer />}
            </ErrorBoundary>
          </div>
        </aside>
      )}
    </div>
  );
}

