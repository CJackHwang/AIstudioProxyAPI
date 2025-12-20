/**
 * Port Configuration Component
 * Configure service ports (changes require restart)
 */

import { useState, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Save, AlertTriangle, Loader2 } from 'lucide-react';
import { fetchPortConfig, updatePortConfig } from '@/api';
import type { PortConfig } from '@/api';
import styles from './SettingsPanel.module.css';

export function PortConfiguration() {
  const queryClient = useQueryClient();
  const [localConfig, setLocalConfig] = useState<PortConfig>({
    fastapi_port: 2048,
    camoufox_debug_port: 9222,
    stream_proxy_port: 3120,
    stream_proxy_enabled: true,
  });
  const [hasChanges, setHasChanges] = useState(false);

  // Fetch current config
  const { data: config, isLoading } = useQuery({
    queryKey: ['portConfig'],
    queryFn: fetchPortConfig,
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
    mutationFn: updatePortConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portConfig'] });
      setHasChanges(false);
    },
  });

  const handleChange = (field: keyof PortConfig, value: number | boolean) => {
    setLocalConfig((prev) => ({ ...prev, [field]: value }));
    setHasChanges(true);
  };

  const handleSave = () => {
    updateMutation.mutate(localConfig);
  };

  const validatePort = (port: number): boolean => {
    return port >= 1024 && port <= 65535;
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
    <div className={styles.portConfig}>
      {/* Restart Warning */}
      {hasChanges && (
        <div className={`${styles.alertBox} ${styles.warning}`}>
          <AlertTriangle size={16} />
          <span>更改将在下次重启服务时生效</span>
        </div>
      )}

      {/* FastAPI Port */}
      <div className={styles.formGroup}>
        <label className={styles.label}>FastAPI 服务端口</label>
        <input
          type="number"
          className={styles.numberInput}
          value={localConfig.fastapi_port}
          min={1024}
          max={65535}
          onChange={(e) => handleChange('fastapi_port', parseInt(e.target.value) || 2048)}
        />
        {!validatePort(localConfig.fastapi_port) && (
          <span className={styles.errorText}>端口必须在 1024-65535 之间</span>
        )}
      </div>

      {/* Camoufox Debug Port */}
      <div className={styles.formGroup}>
        <label className={styles.label}>Camoufox 调试端口</label>
        <input
          type="number"
          className={styles.numberInput}
          value={localConfig.camoufox_debug_port}
          min={1024}
          max={65535}
          onChange={(e) => handleChange('camoufox_debug_port', parseInt(e.target.value) || 9222)}
        />
      </div>

      {/* Stream Proxy Toggle + Port */}
      <div className={styles.toggle}>
        <div className={styles.toggleLabel}>
          <span className={styles.label}>流式代理服务</span>
        </div>
        <button
          className={`${styles.switch} ${localConfig.stream_proxy_enabled ? styles.active : ''}`}
          onClick={() => handleChange('stream_proxy_enabled', !localConfig.stream_proxy_enabled)}
          role="switch"
          aria-checked={localConfig.stream_proxy_enabled}
        >
          <span className={styles.switchThumb} aria-hidden="true" />
        </button>
      </div>

      {localConfig.stream_proxy_enabled && (
        <div className={styles.formGroup}>
          <label className={styles.label}>流式代理端口</label>
          <input
            type="number"
            className={styles.numberInput}
            value={localConfig.stream_proxy_port}
            min={1024}
            max={65535}
            onChange={(e) => handleChange('stream_proxy_port', parseInt(e.target.value) || 3120)}
          />
        </div>
      )}

      {/* Save Button */}
      <div className={styles.buttonGroup}>
        <button
          className={styles.primaryButton}
          onClick={handleSave}
          disabled={!hasChanges || updateMutation.isPending}
        >
          {updateMutation.isPending ? (
            <Loader2 size={14} className={styles.spinning} />
          ) : (
            <Save size={14} />
          )}
          保存配置
        </button>
      </div>
    </div>
  );
}
