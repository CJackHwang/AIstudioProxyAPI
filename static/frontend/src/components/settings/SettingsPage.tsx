/**
 * Settings Page Component
 * Full-page settings dashboard with server control, proxy, auth, ports
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { 
  RefreshCw,
  Server, 
  Shield, 
  Network, 
  Activity,
  Key,
  Loader2,
  CheckCircle,
  AlertCircle
} from 'lucide-react';
import { useI18n } from '@/contexts';
import { ProxySettings } from './ProxySettings';
import { AuthManager } from './AuthManager';
import { PortConfiguration } from './PortConfig';
import { type ApiKeyEntry, getApiKeyValue } from './apiKeys';
import styles from './SettingsPage.module.css';

// API functions
async function fetchServerStatus() {
  const response = await fetch('/api/server/status');
  if (!response.ok) throw new Error('Failed to fetch server status');
  return response.json();
}

async function fetchApiKeys() {
  const response = await fetch('/api/keys');
  if (!response.ok) throw new Error('Failed to fetch API keys');
  return response.json();
}

async function addApiKey(key: string) {
  const response = await fetch('/api/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key }),
  });
  if (!response.ok) throw new Error('Failed to add API key');
  return response.json();
}

async function deleteApiKey(key: string) {
  const response = await fetch('/api/keys', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key }),
  });
  if (!response.ok) throw new Error('Failed to delete API key');
  return response.json();
}

interface ServerStatus {
  status: string;
  uptime_seconds: number;
  uptime_formatted: string;
  launch_mode: string;
  server_port: number;
  stream_port: number;
  version: string;
  python_version: string;
  started_at: string;
}

export function SettingsPage() {
  const { t } = useI18n();
  
  return (
    <div className={styles.settingsPage}>
      <h1 className={styles.pageTitle}>
        <Server size={24} />
        {t.settingsPage.title}
      </h1>
      
      <div className={styles.sections}>
        {/* Minimal Status Bar */}
        <StatusBar />
        
        {/* API Keys */}
        <ApiKeysSection />
        
        {/* Proxy Settings */}
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>
            <Network size={18} />
            {t.settingsPage.proxySettings}
          </h2>
          <p className={styles.sectionDesc}>
            {t.settingsPage.proxyDesc}
          </p>
          <ProxySettings />
        </section>
        
        {/* Auth Management */}
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>
            <Shield size={18} />
            {t.settingsPage.authManagement}
          </h2>
          <p className={styles.sectionDesc}>
            {t.settingsPage.authDesc}
          </p>
          <AuthManager />
        </section>
        
        {/* Port Configuration */}
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>
            <Activity size={18} />
            {t.settingsPage.portConfig}
          </h2>
          <p className={styles.sectionDesc}>
            {t.settingsPage.portDesc}
          </p>
          <PortConfiguration />
        </section>
      </div>
    </div>
  );
}

function StatusBar() {
  const { t } = useI18n();
  const { data: status, isLoading } = useQuery<ServerStatus>({
    queryKey: ['serverStatus'],
    queryFn: fetchServerStatus,
    refetchInterval: 10000,
  });

  if (isLoading) {
    return (
      <div className={styles.statusBar}>
        <Loader2 className={styles.spinning} size={14} />
        <span>{t.settingsPage.loading}</span>
      </div>
    );
  }

  return (
    <div className={styles.statusBar}>
      <span className={styles.statusChip}>
        <CheckCircle size={12} />
        {status?.status || t.common.unknown}
      </span>
      <span className={styles.statusChip}>
        <Activity size={12} />
        {status?.uptime_formatted || '-'}
      </span>
      <span className={styles.statusChip}>
        <Server size={12} />
        {t.settingsPage.port} {status?.server_port || '-'}
      </span>
      <span className={styles.statusChip}>
        {status?.launch_mode || '-'}
      </span>
    </div>
  );
}

function ApiKeysSection() {
  const { t } = useI18n();
  const { data, isLoading, refetch } = useQuery<{ keys: ApiKeyEntry[] }>({
    queryKey: ['apiKeys'],
    queryFn: fetchApiKeys,
  });
  
  const [newKey, setNewKey] = useState('');
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleAdd = async () => {
    if (!newKey.trim()) return;
    setAdding(true);
    setMessage(null);
    try {
      await addApiKey(newKey.trim());
      setNewKey('');
      setMessage({ type: 'success', text: t.settingsPage.keyAdded });
      refetch();
    } catch {
      setMessage({ type: 'error', text: t.settingsPage.addFailed });
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (key: string) => {
    const confirmMsg = t.settingsPage.confirmDelete.replace('{key}', key.substring(0, 8));
    if (!confirm(confirmMsg)) return;
    try {
      await deleteApiKey(key);
      setMessage({ type: 'success', text: t.settingsPage.keyDeleted });
      refetch();
    } catch {
      setMessage({ type: 'error', text: t.settingsPage.deleteFailed });
    }
  };

  if (isLoading) {
    return (
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>
          <Key size={18} />
          {t.settingsPage.apiKeys}
        </h2>
        <div className={styles.loading}>
          <Loader2 className={styles.spinning} size={20} />
        </div>
      </section>
    );
  }

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>
        <Key size={18} />
        {t.settingsPage.apiKeys}
        <button className={styles.refreshButton} onClick={() => refetch()}>
          <RefreshCw size={14} />
        </button>
      </h2>
      <p className={styles.sectionDesc}>
        {t.settingsPage.apiKeysDesc}
      </p>
      <div className={styles.keyList}>
        {data?.keys?.length ? (
          data.keys.map((entry) => {
            const key = getApiKeyValue(entry);
            if (!key) return null;

            return (
              <div key={key} className={styles.keyItem}>
                <code className={styles.keyValue}>{key.substring(0, 16)}...</code>
                <button
                  className={styles.deleteButton}
                  onClick={() => handleDelete(key)}
                >
                  {t.common.delete}
                </button>
              </div>
            );
          })
        ) : (
          <div className={styles.emptyState}>{t.settingsPage.noApiKeys}</div>
        )}
      </div>
      <div className={styles.addKeyForm}>
        <input
          type="text"
          className={styles.input}
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder={t.settingsPage.enterNewKey}
        />
        <button 
          className={styles.addButton}
          onClick={handleAdd}
          disabled={adding || !newKey.trim()}
        >
          {adding ? <Loader2 className={styles.spinning} size={14} /> : null}
          {t.common.add}
        </button>
      </div>
      {message && (
        <div className={`${styles.message} ${styles[message.type]}`}>
          {message.type === 'success' ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {message.text}
        </div>
      )}
    </section>
  );
}
