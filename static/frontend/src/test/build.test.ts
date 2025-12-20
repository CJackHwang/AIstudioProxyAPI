/**
 * Build Verification Tests
 * 
 * These tests ensure the project builds correctly by running typecheck.
 * This catches TypeScript errors BEFORE they break the production build.
 */

import { describe, it, expect } from 'vitest';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const frontendDir = join(__dirname, '..');

describe('Build Verification', () => {
  it('typecheck passes without errors', { timeout: 30000 }, () => {
    // Run tsc --noEmit to check for TypeScript errors
    // This is the same check that runs during `npm run build`
    try {
      execSync('npm run typecheck', {
        cwd: frontendDir,
        encoding: 'utf8',
        stdio: 'pipe',
      });
      // If we get here, typecheck passed
      expect(true).toBe(true);
    } catch (error: unknown) {
      // If typecheck fails, get the error output
      const execError = error as { stdout?: string; stderr?: string };
      const output = execError.stdout || execError.stderr || 'Unknown typecheck error';
      
      // Fail the test with the actual error
      expect.fail(
        `TypeScript errors found. Fix these before committing:\n\n${output}`
      );
    }
  });
});
