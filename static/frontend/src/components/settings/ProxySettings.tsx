/**
 * Proxy Settings Component
 * Configure browser proxy settings with connectivity testing
 */

import { useState, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Wifi, RefreshCw, AlertCircle, CheckCircle, Loader2 } from 'lucide-react';
import { fetchProxyConfig, updateProxyConfig, testProxyConnectivity } from '@/api';
import type { ProxyConfig, ProxyTestResult } from '@/api';
import styles from './SettingsPanel.module.css';

export function ProxySettings() {
  const queryClient = useQueryClient();
  const [localConfig, setLocalConfig] = useState<ProxyConfig>({ enabled: false, address: 'http://127.0.0.1:7890' });
  const [testResult, setTestResult] = useState<ProxyTestResult | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  // Fetch current config
  const { data: config, isLoading } = useQuery({
    queryKey: ['proxyConfig'],
    queryFn: fetchProxyConfig,
  });

  // Update local state when config loads
  useEffect(() => {
    if (config) {
      setLocalConfig(config);
      setHasChanges(false);
    }
  }, [config]);

  // Update config mutation
  const updateMutation = useMutation({
    mutationFn: updateProxyConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxyConfig'] });
      setHasChanges(false);
    },
  });

  // Test connectivity mutation
  const testMutation = useMutation({
    mutationFn: (address: string) => testProxyConnectivity(address),
    onSuccess: (result) => setTestResult(result),
  });

  const handleEnabledChange = (enabled: boolean) => {
    setLocalConfig((prev) => ({ ...prev, enabled }));
    setHasChanges(true);
  };

  const handleAddressChange = (address: string) => {
    setLocalConfig((prev) => ({ ...prev, address }));
    setHasChanges(true);
    setTestResult(null);
  };

  const handleSave = () => {
    updateMutation.mutate(localConfig);
  };

  const handleTest = () => {
    if (localConfig.address.trim()) {
      testMutation.mutate(localConfig.address);
    }
  };

  if (isLoading) {
    return (
      <div className={styles.loading}>
        <Loader2 size={16} className={styles.spinning} />
        <span>加载中...</span>
      </div>
    );
  }

  return (
    <div className={styles.proxySettings}>
      {/* Enable Toggle */}
      <div className={styles.toggle}>
        <div className={styles.toggleLabel}>
          <span className={styles.label}>启用浏览器代理</span>
          <span className={styles.description}>通过代理服务器访问网络</span>
        </div>
        <button
          className={`${styles.switch} ${localConfig.enabled ? styles.active : ''}`}
          onClick={() => handleEnabledChange(!localConfig.enabled)}
          role="switch"
          aria-checked={localConfig.enabled}
        >
          <span className={styles.switchThumb} aria-hidden="true" />
        </button>
      </div>

      {/* Proxy Address Input */}
      <div className={styles.formGroup}>
        <label className={styles.label}>代理地址</label>
        <div className={styles.inputGroup}>
          <input
            type="text"
            className={styles.input}
            value={localConfig.address}
            onChange={(e) => handleAddressChange(e.target.value)}
            placeholder="http://127.0.0.1:7890"
            aria-label="代理地址"
          />
        </div>
      </div>

      {/* Action Buttons */}
      <div className={styles.buttonGroup}>
        <button
          className={styles.secondaryButton}
          onClick={handleTest}
          disabled={!localConfig.address.trim() || testMutation.isPending}
        >
          {testMutation.isPending ? (
            <Loader2 size={14} className={styles.spinning} />
          ) : (
            <Wifi size={14} />
          )}
          测试连接
        </button>
        <button
          className={styles.primaryButton}
          onClick={handleSave}
          disabled={!hasChanges || updateMutation.isPending}
        >
          {updateMutation.isPending ? (
            <Loader2 size={14} className={styles.spinning} />
          ) : (
            <RefreshCw size={14} />
          )}
          保存
        </button>
      </div>

      {/* Test Result */}
      {testResult && (
        <div
          className={`${styles.alertBox} ${testResult.success ? styles.success : styles.error}`}
        >
          {testResult.success ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
          <span>
            {testResult.message}
            {testResult.latency_ms && ` (${testResult.latency_ms}ms)`}
          </span>
        </div>
      )}
    </div>
  );
}
