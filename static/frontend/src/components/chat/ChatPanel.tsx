/**
 * Chat Panel Component
 * Main chat interface with markdown rendering and message actions
 */

import { useRef, useEffect, useState, type KeyboardEvent } from 'react';
import Markdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
// KaTeX CSS is loaded from CDN in index.html to reduce bundle size
import { 
  Send, 
  Square, 
  Trash2, 
  MessageSquare, 
  User, 
  Bot,
  RefreshCw,
  Pencil,
  Check,
  X,
  Loader2,
  Brain,
  ChevronDown,
  AlertCircle
} from 'lucide-react';
import { useChat } from '@/contexts';
import type { ChatMessage } from '@/types';
import styles from './ChatPanel.module.css';

/**
 * Custom hook for elapsed time tracking with capture.
 * Starts counting when isActive becomes true, stops and captures final value when it becomes false.
 * Returns: { liveMs, finalMs, displayMs } where displayMs shows live during active, final after.
 */
function useElapsedTimer(isActive: boolean): { liveMs: number; finalMs: number; displayMs: number } {
  const startTimeRef = useRef<number | null>(null);
  const [liveMs, setLiveMs] = useState(0);
  const [finalMs, setFinalMs] = useState(0);
  const wasActiveRef = useRef(false);

  // Handle activation/deactivation
  useEffect(() => {
    if (isActive && !wasActiveRef.current) {
      // Just became active - start timer
      startTimeRef.current = Date.now();
      setLiveMs(0);
    } else if (!isActive && wasActiveRef.current) {
      // Just became inactive - capture final time
      if (startTimeRef.current !== null) {
        const elapsed = Date.now() - startTimeRef.current;
        setFinalMs(elapsed);
        setLiveMs(elapsed);
        startTimeRef.current = null;
      }
    }
    wasActiveRef.current = isActive;
  }, [isActive]);

  // Tick interval while active
  useEffect(() => {
    if (!isActive || startTimeRef.current === null) return;
    
    const interval = setInterval(() => {
      if (startTimeRef.current !== null) {
        setLiveMs(Date.now() - startTimeRef.current);
      }
    }, 100); // Update every 100ms for smooth display
    
    return () => clearInterval(interval);
  }, [isActive]);

  // displayMs: live while active, final after
  const displayMs = isActive ? liveMs : finalMs;

  return { liveMs, finalMs, displayMs };
}

export function ChatPanel() {
  const { 
    messages, 
    isStreaming, 
    currentStatus,
    sendMessage, 
    clearMessages, 
    stopGeneration,
    regenerateFrom,
    editMessage 
  } = useChat();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [input]);

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return;
    const content = input;
    setInput('');
    await sendMessage(content);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className={styles.chatPanel}>
      {/* Message List */}
      <div className={styles.messageList}>
        {messages.length === 0 ? (
          <div className={styles.emptyState}>
            <MessageSquare className={styles.emptyIcon} />
            <h2 className={styles.emptyTitle}>开始对话</h2>
            <p className={styles.emptyDescription}>
              在下方输入消息，开始与 AI 助手对话
            </p>
          </div>
        ) : (
          messages.map((message, index) => (
            <Message 
              key={message.id} 
              message={message}
              showStatus={isStreaming && index === messages.length - 1 && message.role === 'assistant'}
              currentStatus={currentStatus}
              onEdit={(newContent) => editMessage(message.id, newContent)}
              onRegenerate={() => regenerateFrom(message.id)}
              disabled={isStreaming}
            />
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className={styles.inputArea}>
        <div className={styles.inputWrapper}>
          <textarea
            ref={textareaRef}
            className={styles.textarea}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息... (Shift+Enter 换行)"
            rows={1}
            disabled={isStreaming}
          />
          <div className={styles.actionButtons}>
            {messages.length > 0 && (
              <button
                className={styles.clearButton}
                onClick={clearMessages}
                title="清空对话"
                disabled={isStreaming}
              >
                <Trash2 size={20} />
              </button>
            )}
            {isStreaming ? (
              <button
                className={`${styles.sendButton} ${styles.stopButton}`}
                onClick={stopGeneration}
                title="停止生成"
              >
                <Square size={20} />
              </button>
            ) : (
              <button
                className={styles.sendButton}
                onClick={handleSend}
                disabled={!input.trim()}
                title="发送消息"
              >
                <Send size={20} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// Message Component
function Message({ 
  message, 
  showStatus,
  currentStatus,
  onEdit,
  onRegenerate,
  disabled
}: { 
  message: ChatMessage;
  showStatus?: boolean;
  currentStatus?: string;
  onEdit: (content: string) => void;
  onRegenerate: () => void;
  disabled: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(message.content);
  // Capture both dimensions to match edit area to original message box
  const [editDimensions, setEditDimensions] = useState<{ width?: number; height?: number }>({});
  const editTextareaRef = useRef<HTMLTextAreaElement>(null);
  const messageContentRef = useRef<HTMLDivElement>(null);
  const messageTextRef = useRef<HTMLDivElement>(null);
  const isUser = message.role === 'user';
  
  // Thinking section state - auto-expand while thinking, auto-collapse when done
  const hasThinking = Boolean(message.thinkingContent);
  const [isThinkingExpanded, setIsThinkingExpanded] = useState(message.isThinking ?? false);
  
  // Timer hooks - track total streaming duration and thinking duration
  // The hook now returns displayMs which shows live during active, final after
  const isCurrentlyStreaming = message.isStreaming === true;
  const streamingTimer = useElapsedTimer(isCurrentlyStreaming);
  
  const isActivelyThinking = message.isThinking === true;
  const thinkingTimer = useElapsedTimer(isActivelyThinking);
  
  // Convert to seconds for display (minimum 1s if any time recorded)
  const totalSeconds = streamingTimer.displayMs > 0 ? Math.max(1, Math.floor(streamingTimer.displayMs / 1000)) : 0;
  const thinkingSeconds = thinkingTimer.displayMs > 0 ? Math.max(1, Math.floor(thinkingTimer.displayMs / 1000)) : 0;
  
  // Auto-collapse thinking when thinking phase ends
  useEffect(() => {
    if (message.isThinking) {
      setIsThinkingExpanded(true);
    } else if (hasThinking && !message.isStreaming) {
      // Thinking done and streaming finished - collapse
      setIsThinkingExpanded(false);
    }
  }, [message.isThinking, message.isStreaming, hasThinking]);

  // Start editing: capture dimensions and sync content
  const startEditing = () => {
    const width = messageContentRef.current?.offsetWidth;
    const height = messageTextRef.current?.offsetHeight;
    setEditDimensions({ width, height });
    setEditContent(message.content);
    setIsEditing(true);
  };

  // Auto-resize textarea to fit content
  useEffect(() => {
    if (isEditing && editTextareaRef.current) {
      const textarea = editTextareaRef.current;
      textarea.style.height = 'auto';
      textarea.style.height = `${textarea.scrollHeight}px`;
    }
  }, [isEditing, editContent]);
  
  const handleSaveEdit = () => {
    if (editContent.trim()) {
      onEdit(editContent.trim());
      setIsEditing(false);
    }
  };

  const handleCancelEdit = () => {
    setEditContent(message.content);
    setIsEditing(false);
  };
  
  // Format seconds as MM:SS or just SS if under 1 minute
  const formatTime = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className={`${styles.message} ${isUser ? styles.user : styles.assistant}`}>
      <div className={`${styles.avatar} ${isUser ? styles.user : styles.assistant}`}>
        {message.isStreaming ? (
          <Loader2 size={16} className={styles.spinningIcon} />
        ) : isUser ? (
          <User size={16} />
        ) : (
          <Bot size={16} />
        )}
      </div>
      <div className={styles.messageWrapper}>
        {/* Collapsible thinking section for AI messages - ABOVE the message content */}
        {!isUser && hasThinking && (
          <div className={`${styles.thinkingSection} ${isThinkingExpanded ? styles.expanded : styles.collapsed} ${message.error ? styles.thinkingError : ''}`}>
            <button 
              className={styles.thinkingHeader}
              onClick={() => setIsThinkingExpanded(!isThinkingExpanded)}
              type="button"
            >
              <div className={styles.thinkingHeaderLeft}>
                {message.error ? (
                  <AlertCircle size={14} className={styles.errorIcon} />
                ) : (
                  <Brain size={14} className={message.isThinking ? styles.spinningIcon : ''} />
                )}
                <span>{message.error ? '思考中断' : message.isThinking ? '正在思考' : '思考过程'}</span>
              </div>
              <div className={styles.thinkingHeaderRight}>
                {!message.error && (
                  <span className={styles.thinkingTimer}>{formatTime(thinkingSeconds)}</span>
                )}
                <ChevronDown 
                  size={14} 
                  className={`${styles.thinkingChevron} ${isThinkingExpanded ? styles.rotated : ''}`} 
                />
              </div>
            </button>
            {isThinkingExpanded && (
              <div className={styles.thinkingContent}>
                <Markdown
                  remarkPlugins={[remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                >
                  {message.thinkingContent || ''}
                </Markdown>
              </div>
            )}
          </div>
        )}
        
        <div ref={messageContentRef} className={styles.messageContent}>
          {isEditing ? (
            <div className={styles.editArea} style={editDimensions.width ? { width: editDimensions.width } : undefined}>
              <textarea
                ref={editTextareaRef}
                className={styles.editTextarea}
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                autoFocus
              />
              <div className={styles.editActions}>
                <button 
                  className={styles.editActionButton}
                  onClick={handleSaveEdit}
                  title="保存"
                >
                  <Check size={14} /> 保存
                </button>
                <button 
                  className={`${styles.editActionButton} ${styles.cancel}`}
                  onClick={handleCancelEdit}
                  title="取消"
                >
                  <X size={14} /> 取消
                </button>
              </div>
            </div>
          ) : (
            <>
              <div ref={messageTextRef} className={styles.messageText}>
                {isUser ? (
                  // User messages: plain text
                  message.content
                ) : (
                  // AI messages: markdown with LaTeX support
                  <Markdown
                    remarkPlugins={[remarkMath]}
                    rehypePlugins={[rehypeKatex]}
                    components={{
                      // Better code block rendering
                      code({ className, children, ...props }) {
                        const match = /language-(\w+)/.exec(className || '');
                        return match ? (
                          <pre className={styles.codeBlock}>
                            <code className={className} {...props}>
                              {children}
                            </code>
                          </pre>
                        ) : (
                          <code className={styles.inlineCode} {...props}>
                            {children}
                          </code>
                        );
                      },
                    }}
                  >
                    {message.content}
                  </Markdown>
                )}
                {message.isStreaming && <span className={styles.streamingCursor} />}
              </div>
              {message.error && (
                <div className={styles.messageError}>{message.error}</div>
              )}
            </>
          )}
        </div>
        {/* Status display with total timer during streaming */}
        {showStatus && currentStatus && (
          <div className={styles.statusBar}>
            <Loader2 size={12} className={styles.spinningIcon} />
            <span>{currentStatus}</span>
            {/* Show total timer (thinking + response) during streaming */}
            <span className={styles.responseTimer}>{formatTime(totalSeconds)}</span>
          </div>
        )}

        {/* Total time badge - always visible for AI messages with time */}
        {!isUser && !message.isStreaming && totalSeconds > 0 && (
          <div className={styles.totalTimeBadge}>
            <span>总耗时 {formatTime(totalSeconds)}</span>
          </div>
        )}

        {/* Action buttons - both message types have edit and regen */}
        {!isEditing && !message.isStreaming && (
          <div className={styles.messageActions}>
            <button 
              className={styles.actionButton}
              onClick={startEditing}
              disabled={disabled}
              title="编辑消息"
            >
              <Pencil size={14} />
            </button>
            <button 
              className={styles.actionButton}
              onClick={onRegenerate}
              disabled={disabled}
              title={isUser ? "重新发送" : "重新生成"}
            >
              <RefreshCw size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
