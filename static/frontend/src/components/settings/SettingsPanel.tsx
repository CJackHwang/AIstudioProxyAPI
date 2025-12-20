/**
 * Settings Panel Component
 * Model settings and parameters with DYNAMIC thinking controls from backend API
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw, ChevronDown, ChevronRight, AlertCircle, Loader2 } from 'lucide-react';
import { useSettings } from '@/contexts';
import { fetchModels } from '@/api';
import { useModelCapabilities } from '@/hooks/useModelCapabilities';
import type { ThinkingLevel } from '@/types';
import styles from './SettingsPanel.module.css';

export function SettingsPanel() {
  const { settings, dispatch, selectedModel, setSelectedModel } = useSettings();
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    model: true,
    thinking: true,
    params: true,
    tools: true,
    system: false,
  });
  
  // Fetch models
  const { data: modelsData, isLoading: modelsLoading, refetch } = useQuery({
    queryKey: ['models'],
    queryFn: fetchModels,
    staleTime: 60000,
  });

  // Fetch model capabilities from backend (single source of truth)
  const { 
    getModelCategory, 
    getModelCapabilities, 
    isLoading: capabilitiesLoading 
  } = useModelCapabilities();

  const models = modelsData?.data || [];
  const category = getModelCategory(selectedModel);
  const capabilities = getModelCapabilities(selectedModel);

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  // Build thinking level options from capabilities
  const buildLevelOptions = (): { value: ThinkingLevel | ''; label: string }[] => {
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
  };

  const levelOptions = buildLevelOptions();

  // Get budget slider range from capabilities
  const getBudgetRange = () => {
    if (capabilities?.budgetRange) {
      return { min: capabilities.budgetRange[0], max: capabilities.budgetRange[1] };
    }
    return { min: 512, max: 24576 };
  };

  return (
    <div className={styles.settingsPanel}>
      {/* Model Selection */}
      <CollapsibleSection 
        title="模型选择" 
        expanded={expandedSections.model}
        onToggle={() => toggleSection('model')}
      >
        <div className={styles.formGroup}>
          <label className={styles.label}>当前模型</label>
          <select
            className={styles.select}
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            disabled={modelsLoading}
            aria-label="选择模型"
          >
            {models.length === 0 && (
              <option value="">加载中...</option>
            )}
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.id}
              </option>
            ))}
          </select>
        </div>
        <button 
          className={styles.refreshButton}
          onClick={() => refetch()}
          aria-label="刷新模型列表"
        >
          <RefreshCw size={14} aria-hidden="true" />
          刷新模型列表
        </button>
      </CollapsibleSection>

      {/* Thinking Settings - Dynamic UI based on backend capabilities */}
      <CollapsibleSection 
        title="思考设置" 
        expanded={expandedSections.thinking}
        onToggle={() => toggleSection('thinking')}
      >
        {capabilitiesLoading ? (
          <div className={styles.loading}>
            <Loader2 size={16} className={styles.spinning} />
            <span>加载中...</span>
          </div>
        ) : capabilities?.thinkingType === 'level' ? (
          /* Level selector (Gemini 3) */
          <div className={styles.formGroup}>
            <label className={styles.label}>思考等级</label>
            <select
              className={styles.select}
              value={settings.thinkingLevel}
              onChange={(e) => 
                dispatch({ type: 'SET_THINKING_LEVEL', payload: e.target.value })
              }
              aria-label="选择思考等级"
            >
              {levelOptions.map((level) => (
                <option key={level.value} value={level.value}>
                  {level.label}
                </option>
              ))}
            </select>
            <span className={styles.description}>
              {category} 支持 {capabilities.levels?.length || 0} 个等级
            </span>
          </div>
        ) : capabilities?.thinkingType === 'budget' ? (
          /* Budget controls (Gemini 2.5) */
          <>
            <Toggle
              label="思考模式"
              description={capabilities.alwaysOn 
                ? "此模型始终启用思考模式" 
                : "启用模型的深度思考能力"
              }
              checked={capabilities.alwaysOn ? true : settings.enableThinking}
              disabled={capabilities.alwaysOn}
              onChange={(checked) => 
                dispatch({ type: 'SET_ENABLE_THINKING', payload: checked })
              }
            />
            {(capabilities.alwaysOn || settings.enableThinking) && (
              <>
                <Toggle
                  label="限制思考预算"
                  description="手动限制模型思考的 token 数量"
                  checked={settings.enableManualBudget}
                  onChange={(checked) => 
                    dispatch({ type: 'SET_ENABLE_MANUAL_BUDGET', payload: checked })
                  }
                />
                {settings.enableManualBudget && (
                  <Slider
                    label="思考预算"
                    value={settings.thinkingBudget}
                    min={getBudgetRange().min}
                    max={getBudgetRange().max}
                    step={128}
                    onChange={(value) => 
                      dispatch({ type: 'SET_THINKING_BUDGET', payload: value })
                    }
                  />
                )}
              </>
            )}
          </>
        ) : (
          /* No thinking support */
          <div className={styles.infoBox}>
            <AlertCircle size={16} aria-hidden="true" />
            <span>当前模型不支持思考模式配置。</span>
          </div>
        )}
      </CollapsibleSection>

      {/* Parameters */}
      <CollapsibleSection 
        title="生成参数" 
        expanded={expandedSections.params}
        onToggle={() => toggleSection('params')}
      >
        <Slider
          label="温度"
          value={settings.temperature}
          min={0}
          max={2}
          step={0.01}
          onChange={(value) => 
            dispatch({ type: 'SET_TEMPERATURE', payload: value })
          }
        />
        <Slider
          label="最大令牌数"
          value={settings.maxOutputTokens}
          min={1}
          max={65536}
          step={1}
          onChange={(value) => 
            dispatch({ type: 'SET_MAX_TOKENS', payload: value })
          }
        />
        <Slider
          label="Top P"
          value={settings.topP}
          min={0}
          max={1}
          step={0.01}
          onChange={(value) => 
            dispatch({ type: 'SET_TOP_P', payload: value })
          }
        />
      </CollapsibleSection>

      {/* Tools */}
      <CollapsibleSection 
        title="工具" 
        expanded={expandedSections.tools}
        onToggle={() => toggleSection('tools')}
      >
        <Toggle
          label="Google 搜索"
          description={capabilities?.supportsGoogleSearch === false 
            ? "此模型不支持 Google 搜索" 
            : "允许模型搜索网络信息"
          }
          checked={capabilities?.supportsGoogleSearch === false ? false : settings.enableGoogleSearch}
          disabled={capabilities?.supportsGoogleSearch === false}
          onChange={(checked) => 
            dispatch({ type: 'SET_ENABLE_GOOGLE_SEARCH', payload: checked })
          }
        />
      </CollapsibleSection>

      {/* System Prompt */}
      <CollapsibleSection 
        title="系统提示" 
        expanded={expandedSections.system}
        onToggle={() => toggleSection('system')}
      >
        <textarea
          className={styles.textarea}
          value={settings.systemPrompt}
          onChange={(e) => 
            dispatch({ type: 'SET_SYSTEM_PROMPT', payload: e.target.value })
          }
          placeholder="输入系统提示词..."
          aria-label="系统提示词"
        />
      </CollapsibleSection>
    </div>
  );
}

// Collapsible Section Component
function CollapsibleSection({
  title,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className={styles.section}>
      <button 
        className={styles.sectionHeader} 
        onClick={onToggle}
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
        <span>{title}</span>
      </button>
      <div className={`${styles.sectionContent} ${expanded ? styles.expanded : ''}`}>
        {children}
      </div>
    </div>
  );
}

// Slider Component
function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className={styles.formGroup}>
      <label className={styles.label}>{label}</label>
      <div className={styles.sliderGroup}>
        <input
          type="range"
          className={styles.slider}
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          aria-label={label}
        />
        <input
          type="number"
          className={styles.sliderInput}
          value={step < 1 ? value.toFixed(2) : value}
          min={min}
          max={max}
          step={step}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            if (!isNaN(v)) onChange(v);
          }}
          aria-label={`${label} 数值`}
        />
      </div>
    </div>
  );
}

// Toggle Component
function Toggle({
  label,
  description,
  checked,
  disabled = false,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className={`${styles.toggle} ${disabled ? styles.disabled : ''}`}>
      <div className={styles.toggleLabel}>
        <span className={styles.label}>{label}</span>
        {description && <span className={styles.description}>{description}</span>}
      </div>
      <button
        className={`${styles.switch} ${checked ? styles.active : ''}`}
        onClick={() => !disabled && onChange(!checked)}
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
      >
        <span className={styles.switchThumb} aria-hidden="true" />
      </button>
    </div>
  );
}
