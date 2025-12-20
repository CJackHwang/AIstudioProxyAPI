/**
 * Chat Context
 * Manages chat messages, streaming, and message editing/regeneration
 */

import { 
  createContext, 
  useContext, 
  useReducer, 
  useCallback,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { ChatMessage, Message, Tool } from '@/types';
import { streamChatCompletion } from '@/api';
import { useSettings } from './SettingsContext';

// Generate unique ID
const generateId = () => Math.random().toString(36).substring(2, 11);

// Actions
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

interface ChatState {
  messages: ChatMessage[];
}

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

interface ChatContextValue {
  messages: ChatMessage[];
  isStreaming: boolean;
  currentStatus: string;
  sendMessage: (content: string) => Promise<void>;
  clearMessages: () => void;
  stopGeneration: () => void;
  regenerateFrom: (messageId: string) => Promise<void>;
  editMessage: (messageId: string, newContent: string) => Promise<void>;
}

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(chatReducer, { messages: [] });
  const { settings, selectedModel } = useSettings();
  const abortControllerRef = useRef<AbortController | null>(null);
  const [currentStatus, setCurrentStatus] = useState('');

  const isStreaming = state.messages.some(m => m.isStreaming);

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setCurrentStatus('');
  }, []);

  // Build request from messages
  const buildRequest = useCallback((messages: ChatMessage[]) => {
    const apiMessages: Message[] = [];
    
    // Add system prompt if present
    if (settings.systemPrompt) {
      apiMessages.push({ role: 'system', content: settings.systemPrompt });
    }
    
    // Add conversation history
    messages.forEach(m => {
      apiMessages.push({ role: m.role, content: m.content });
    });

    // Determine reasoning_effort based on model
    let reasoning_effort: 'minimal' | 'low' | 'medium' | 'high' | number | undefined;
    const modelId = selectedModel.toLowerCase();
    
    if (modelId.includes('gemini-3')) {
      // Gemini 3: use level
      if (settings.thinkingLevel) {
        reasoning_effort = settings.thinkingLevel as 'minimal' | 'low' | 'medium' | 'high';
      }
    } else if (modelId.includes('gemini-2.5') || 
               modelId === 'gemini-flash-latest' || 
               modelId === 'gemini-flash-lite-latest') {
      // Gemini 2.5 and flash-latest variants: use budget if enabled
      if (settings.enableThinking && settings.enableManualBudget) {
        reasoning_effort = settings.thinkingBudget;
      }
    } else if (modelId.includes('flash') && settings.enableThinking) {
      // Other flash models: use budget if thinking enabled
      if (settings.enableManualBudget) {
        reasoning_effort = settings.thinkingBudget;
      }
    }

    // Build tools array based on settings
    const tools: Tool[] = [];
    if (settings.enableGoogleSearch) {
      tools.push({ google_search_retrieval: {} });
    }

    return {
      model: selectedModel,
      messages: apiMessages,
      temperature: settings.temperature,
      max_output_tokens: settings.maxOutputTokens,
      top_p: settings.topP,
      reasoning_effort,
      tools: tools.length > 0 ? tools : undefined,
      tool_choice: tools.length > 0 ? 'auto' : undefined,
    };
  }, [selectedModel, settings]);

  const sendMessage = useCallback(async (content: string) => {
    if (!content.trim() || !selectedModel) return;

    // Add user message
    const userMessage: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: content.trim(),
      timestamp: new Date(),
    };
    dispatch({ type: 'ADD_MESSAGE', payload: userMessage });

    // Prepare assistant message placeholder
    const assistantMessage: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
    };
    dispatch({ type: 'ADD_MESSAGE', payload: assistantMessage });

    // Build request with current messages + new user message
    const currentMessages = [...state.messages, userMessage];
    const request = buildRequest(currentMessages);

    // Create abort controller
    abortControllerRef.current = new AbortController();
    setCurrentStatus('正在连接...');

    try {
      const stream = streamChatCompletion(request, abortControllerRef.current.signal);
      let hasReceivedContent = false;

      for await (const chunk of stream) {
        const delta = chunk.choices[0]?.delta;
        const reasoningContent = delta?.reasoning_content;
        const content = delta?.content;
        
        // Handle thinking content
        if (reasoningContent) {
          setCurrentStatus('正在思考...');
          dispatch({
            type: 'UPDATE_THINKING',
            payload: { id: assistantMessage.id, thinkingContent: reasoningContent },
          });
        }
        
        // Handle main content
        if (content) {
          // First content chunk marks end of thinking phase
          if (!hasReceivedContent) {
            hasReceivedContent = true;
            dispatch({ type: 'SET_THINKING_DONE', payload: { id: assistantMessage.id } });
            setCurrentStatus('正在生成...');
          }
          dispatch({
            type: 'UPDATE_MESSAGE',
            payload: { id: assistantMessage.id, content },
          });
        }
      }

      dispatch({
        type: 'SET_STREAMING',
        payload: { id: assistantMessage.id, isStreaming: false },
      });
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        dispatch({
          type: 'SET_STREAMING',
          payload: { id: assistantMessage.id, isStreaming: false },
        });
      } else {
        dispatch({
          type: 'SET_ERROR',
          payload: {
            id: assistantMessage.id,
            error: error instanceof Error ? error.message : '发生未知错误',
          },
        });
      }
    } finally {
      abortControllerRef.current = null;
      setCurrentStatus('');
    }
  }, [selectedModel, state.messages, buildRequest]);

  const regenerateFrom = useCallback(async (messageId: string) => {
    // Find the message to regenerate
    const index = state.messages.findIndex(m => m.id === messageId);
    if (index === -1) return;

    // Get messages before this one (for context)
    const previousMessages = state.messages.slice(0, index);
    
    // Remove this message and all after
    dispatch({ type: 'REMOVE_MESSAGES_FROM', payload: messageId });

    // Add new assistant placeholder
    const assistantMessage: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
    };
    dispatch({ type: 'ADD_MESSAGE', payload: assistantMessage });

    // Build request
    const request = buildRequest(previousMessages);
    abortControllerRef.current = new AbortController();
    setCurrentStatus('正在重新生成...');

    try {
      const stream = streamChatCompletion(request, abortControllerRef.current.signal);
      let hasReceivedContent = false;

      for await (const chunk of stream) {
        const delta = chunk.choices[0]?.delta;
        const reasoningContent = delta?.reasoning_content;
        const content = delta?.content;
        
        if (reasoningContent) {
          setCurrentStatus('正在思考...');
          dispatch({
            type: 'UPDATE_THINKING',
            payload: { id: assistantMessage.id, thinkingContent: reasoningContent },
          });
        }
        
        if (content) {
          if (!hasReceivedContent) {
            hasReceivedContent = true;
            dispatch({ type: 'SET_THINKING_DONE', payload: { id: assistantMessage.id } });
            setCurrentStatus('正在生成...');
          }
          dispatch({
            type: 'UPDATE_MESSAGE',
            payload: { id: assistantMessage.id, content },
          });
        }
      }

      dispatch({
        type: 'SET_STREAMING',
        payload: { id: assistantMessage.id, isStreaming: false },
      });
    } catch (error) {
      if (!(error instanceof Error && error.name === 'AbortError')) {
        dispatch({
          type: 'SET_ERROR',
          payload: {
            id: assistantMessage.id,
            error: error instanceof Error ? error.message : '发生未知错误',
          },
        });
      }
    } finally {
      abortControllerRef.current = null;
      setCurrentStatus('');
    }
  }, [state.messages, buildRequest]);

  const editMessage = useCallback(async (messageId: string, newContent: string) => {
    // Find the message
    const index = state.messages.findIndex(m => m.id === messageId);
    if (index === -1) return;

    // Update the message content
    dispatch({ 
      type: 'SET_MESSAGE_CONTENT', 
      payload: { id: messageId, content: newContent } 
    });

    // If it's a user message, regenerate the response
    const message = state.messages[index];
    if (message.role === 'user') {
      // Remove all messages after this one
      const messagesAfter = state.messages.slice(index + 1);
      messagesAfter.forEach(m => {
        dispatch({ type: 'REMOVE_MESSAGES_FROM', payload: m.id });
      });

      // Get updated messages
      const updatedMessages = state.messages.slice(0, index + 1);
      updatedMessages[index] = { ...updatedMessages[index], content: newContent };

      // Add assistant placeholder
      const assistantMessage: ChatMessage = {
        id: generateId(),
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        isStreaming: true,
      };
      dispatch({ type: 'ADD_MESSAGE', payload: assistantMessage });

      // Build and send request
      const request = buildRequest(updatedMessages);
      abortControllerRef.current = new AbortController();
      setCurrentStatus('正在生成回复...');

      try {
        const stream = streamChatCompletion(request, abortControllerRef.current.signal);
        let hasReceivedContent = false;

        for await (const chunk of stream) {
          const delta = chunk.choices[0]?.delta;
          const reasoningContent = delta?.reasoning_content;
          const content = delta?.content;
          
          if (reasoningContent) {
            setCurrentStatus('正在思考...');
            dispatch({
              type: 'UPDATE_THINKING',
              payload: { id: assistantMessage.id, thinkingContent: reasoningContent },
            });
          }
          
          if (content) {
            if (!hasReceivedContent) {
              hasReceivedContent = true;
              dispatch({ type: 'SET_THINKING_DONE', payload: { id: assistantMessage.id } });
              setCurrentStatus('正在生成...');
            }
            dispatch({
              type: 'UPDATE_MESSAGE',
              payload: { id: assistantMessage.id, content },
            });
          }
        }

        dispatch({
          type: 'SET_STREAMING',
          payload: { id: assistantMessage.id, isStreaming: false },
        });
      } catch (error) {
        if (!(error instanceof Error && error.name === 'AbortError')) {
          dispatch({
            type: 'SET_ERROR',
            payload: {
              id: assistantMessage.id,
              error: error instanceof Error ? error.message : '发生未知错误',
            },
          });
        }
      } finally {
        abortControllerRef.current = null;
        setCurrentStatus('');
      }
    }
  }, [state.messages, buildRequest]);

  const clearMessages = useCallback(() => {
    stopGeneration();
    dispatch({ type: 'CLEAR_MESSAGES' });
  }, [stopGeneration]);

  return (
    <ChatContext.Provider
      value={{
        messages: state.messages,
        isStreaming,
        currentStatus,
        sendMessage,
        clearMessages,
        stopGeneration,
        regenerateFrom,
        editMessage,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChat(): ChatContextValue {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return context;
}
