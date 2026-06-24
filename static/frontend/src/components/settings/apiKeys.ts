export type ApiKeyEntry = string | { key?: string; value?: string };

export function getApiKeyValue(key: ApiKeyEntry) {
  return typeof key === 'string' ? key : key.key || key.value || '';
}
