// @ai-module: Mock Data Seeds
// @ai-role: Static seed data and in-memory mutable file content map used by all three Zustand stores.
//           Also exports the AgentRole type re-export (legacy — prefer importing AgentRole from types/index.ts).
//           This file is the boundary between "initial state" and "runtime state".
// @ai-dependencies: types/index.ts (FileNode, AgentMessage, Task, LogLine, AgentRole)

// [AI-STRICT] mockEditorFiles is a MUTABLE in-memory map, NOT Zustand state.
//             It is intentionally outside Zustand because Monaco Editor reads content synchronously via
//             fileStore.getActiveContent() which calls mockEditorFiles[activeTabId].content.
//             When the real backend is connected, move file content into Zustand state and remove this map.
// [AI-STRICT] DO NOT import mockEditorFiles into UI components or hooks other than fileStore.ts and agentSimulation.ts.
//             Any component that needs file content must go through useFileSystem().activeFileContent.
// [AI-STRICT] initialAgentMessages, initialTasks, and initialTerminalLines are reset seeds.
//             They must not be mutated — they are spread/copied on every reset in agentStore.resetToInitial()
//             and useSimulation.resetSimulation(). Add new seed entries only when updating the demo scenario.


import type { FileNode, AgentMessage, Task, LogLine, AgentRole } from '../types';

export { AgentRole };

export const fileTree: FileNode[] = [
  {
    id: 'src',
    name: 'src',
    type: 'folder',
    children: [
      {
        id: 'src-components',
        name: 'components',
        type: 'folder',
        children: [
          { id: 'authform', name: 'AuthForm.tsx', type: 'file', language: 'typescript' },
          { id: 'button', name: 'Button.tsx', type: 'file', language: 'typescript' },
          { id: 'input', name: 'Input.tsx', type: 'file', language: 'typescript' },
          { id: 'modal', name: 'Modal.tsx', type: 'file', language: 'typescript' },
        ],
      },
      {
        id: 'src-hooks',
        name: 'hooks',
        type: 'folder',
        children: [
          { id: 'useauth', name: 'useAuth.ts', type: 'file', language: 'typescript' },
          { id: 'useform', name: 'useForm.ts', type: 'file', language: 'typescript' },
        ],
      },
      {
        id: 'src-lib',
        name: 'lib',
        type: 'folder',
        children: [
          { id: 'supabase', name: 'supabase.ts', type: 'file', language: 'typescript' },
          { id: 'utils', name: 'utils.ts', type: 'file', language: 'typescript' },
        ],
      },
      { id: 'app', name: 'App.tsx', type: 'file', language: 'typescript' },
      { id: 'main', name: 'main.tsx', type: 'file', language: 'typescript' },
      { id: 'indexcss', name: 'index.css', type: 'file', language: 'css' },
    ],
  },
  {
    id: 'public',
    name: 'public',
    type: 'folder',
    children: [
      { id: 'favicon', name: 'favicon.ico', type: 'file' },
      { id: 'logo', name: 'logo.svg', type: 'file' },
    ],
  },
  { id: 'pkgjson', name: 'package.json', type: 'file', language: 'json' },
  { id: 'tsconfig', name: 'tsconfig.json', type: 'file', language: 'json' },
  { id: 'viteconfig', name: 'vite.config.ts', type: 'file', language: 'typescript' },
  { id: 'tailwindconfig', name: 'tailwind.config.js', type: 'file', language: 'javascript' },
];

export const initialAgentMessages: AgentMessage[] = [
  {
    id: '1',
    agent: 'tech-lead',
    agentLabel: 'Tech Lead',
    content: 'Received goal: Build a login form. Breaking down into subtasks and delegating to team.',
    timestamp: '14:01:02',
  },
  {
    id: '2',
    agent: 'tech-lead',
    agentLabel: 'Tech Lead',
    content: 'Task plan created: (1) Scaffold auth components, (2) Implement form logic, (3) Add validation, (4) Write tests.',
    timestamp: '14:01:04',
  },
  {
    id: '3',
    agent: 'dev',
    agentLabel: 'Dev',
    content: 'Acknowledged. Starting on AuthForm.tsx — creating email/password inputs with controlled state.',
    timestamp: '14:01:07',
  },
  {
    id: '4',
    agent: 'dev',
    agentLabel: 'Dev',
    content: 'AuthForm.tsx drafted. Integrating useForm hook for validation logic. Also setting up Supabase client in lib/supabase.ts.',
    timestamp: '14:01:15',
  },
  {
    id: '5',
    agent: 'qa',
    agentLabel: 'QA',
    content: 'Reviewing AuthForm.tsx. Found: missing aria-label on inputs, no error boundary on async signIn call.',
    timestamp: '14:01:22',
  },
  {
    id: '6',
    agent: 'dev',
    agentLabel: 'Dev',
    content: 'Fixed: added aria-labels and wrapped signIn in try/catch with user-facing error state. Updating component now.',
    timestamp: '14:01:29',
  },
  {
    id: '7',
    agent: 'qa',
    agentLabel: 'QA',
    content: 'Running unit tests on useForm hook. All 8 assertions pass. Edge case: empty submit correctly blocked.',
    timestamp: '14:01:37',
  },
  {
    id: '8',
    agent: 'tech-lead',
    agentLabel: 'Tech Lead',
    content: 'Good progress. Dev, please also add a "Forgot Password" flow stub. QA, begin integration tests next.',
    timestamp: '14:01:44',
  },
  {
    id: '9',
    agent: 'dev',
    agentLabel: 'Dev',
    content: 'Added ForgotPassword modal stub. Wired to Modal.tsx component. Ready for QA review.',
    timestamp: '14:01:52',
  },
  {
    id: '10',
    agent: 'qa',
    agentLabel: 'QA',
    content: 'Integration test: Login flow end-to-end passing. Modal opens/closes correctly. No console errors detected.',
    timestamp: '14:02:01',
  },
  {
    id: '11',
    agent: 'tech-lead',
    agentLabel: 'Tech Lead',
    content: 'All tasks complete. Merging auth feature. Preparing CSS refactor pass as next goal.',
    timestamp: '14:02:08',
  },
];

export const initialTasks: Task[] = [
  {
    id: 't1',
    label: 'Setup project scaffold',
    status: 'completed',
    agent: 'tech-lead',
    subtasks: ['Initialize Vite + React', 'Configure Tailwind CSS', 'Setup Supabase client'],
  },
  {
    id: 't2',
    label: 'Build AuthForm component',
    status: 'completed',
    agent: 'dev',
    subtasks: ['Create email/password inputs', 'Add controlled state', 'Integrate useForm hook'],
  },
  {
    id: 't3',
    label: 'Implement form validation',
    status: 'completed',
    agent: 'dev',
    subtasks: ['Validate email format', 'Password length check', 'Disable submit on invalid'],
  },
  {
    id: 't4',
    label: 'Write unit tests for useForm',
    status: 'completed',
    agent: 'qa',
    subtasks: ['Test empty submit', 'Test invalid email', 'Test valid submission'],
  },
  {
    id: 't5',
    label: 'Add ForgotPassword modal',
    status: 'in-progress',
    agent: 'dev',
    subtasks: ['Create Modal.tsx', 'Wire open/close state', 'Add email reset form'],
  },
  {
    id: 't6',
    label: 'Integration tests for auth flow',
    status: 'in-progress',
    agent: 'qa',
    subtasks: ['End-to-end login test', 'Error state handling', 'Redirect after login'],
  },
  {
    id: 't7',
    label: 'Refactor global CSS',
    status: 'pending',
    agent: 'dev',
    subtasks: ['Audit unused classes', 'Extract component utilities', 'Purge dead styles'],
  },
  {
    id: 't8',
    label: 'Accessibility audit',
    status: 'pending',
    agent: 'qa',
    subtasks: ['Check ARIA labels', 'Keyboard navigation', 'Color contrast ratio'],
  },
  {
    id: 't9',
    label: 'Deploy to staging',
    status: 'pending',
    agent: 'tech-lead',
    subtasks: ['Configure env vars', 'Run production build', 'Verify on Vercel preview'],
  },
];

let lineIdCounter = 0;
function line(text: string, type: LogLine['type']): LogLine {
  return { id: `init-${lineIdCounter++}`, text, type };
}

export const initialTerminalLines: LogLine[] = [
  line('$ npm install', 'command'),
  line('npm warn deprecated inflight@1.0.6', 'warn'),
  line('added 284 packages in 4.2s', 'info'),
  line('', 'blank'),
  line('$ vite build', 'command'),
  line('vite v5.4.2 building for production...', 'info'),
  line('✓ 47 modules transformed.', 'success'),
  line('dist/index.html                   0.46 kB │ gzip:  0.30 kB', 'output'),
  line('dist/assets/index-BmEyv9sZ.css   14.32 kB │ gzip:  3.82 kB', 'output'),
  line('dist/assets/index-Cq7jlvDB.js  312.44 kB │ gzip: 98.11 kB', 'output'),
  line('✓ built in 1.84s', 'success'),
  line('', 'blank'),
  line('$ vitest run', 'command'),
  line('RUN  v1.3.1', 'info'),
  line('', 'blank'),
  line(' ✓ src/hooks/useForm.test.ts (8 tests) 12ms', 'success'),
  line(' ✓ src/components/AuthForm.test.tsx (5 tests) 28ms', 'success'),
  line(' ✓ src/components/Button.test.tsx (3 tests) 9ms', 'success'),
  line(' ✗ src/components/Modal.test.tsx (2 tests) 41ms', 'error'),
  line('   FAIL: Modal closes on backdrop click — expected true, got false', 'error'),
  line('', 'blank'),
  line('Test Files  3 passed | 1 failed (4)', 'warn'),
  line('Tests       16 passed | 1 failed (17)', 'warn'),
  line('Duration    312ms', 'info'),
  line('', 'blank'),
  line('$ _', 'cursor'),
];

export const mockEditorFiles: Record<string, { content: string; language: string }> = {
  'App.tsx': {
    language: 'typescript',
    content: `import { useState } from 'react';
import { AuthForm } from './components/AuthForm';
import { Modal } from './components/Modal';
import { useAuth } from './hooks/useAuth';

export default function App() {
  const { user, loading } = useAuth();
  const [showForgotPassword, setShowForgotPassword] = useState(false);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-sky-400" />
      </div>
    );
  }

  if (user) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center">
        <div className="text-center space-y-4">
          <h1 className="text-2xl font-semibold">Welcome back, {user.email}</h1>
          <p className="text-slate-400">You are logged in.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-slate-100">Sign in</h1>
          <p className="mt-2 text-sm text-slate-400">
            Access your account to continue
          </p>
        </div>
        <AuthForm onForgotPassword={() => setShowForgotPassword(true)} />
        <Modal
          open={showForgotPassword}
          onClose={() => setShowForgotPassword(false)}
          title="Reset Password"
        >
          <ForgotPasswordForm onClose={() => setShowForgotPassword(false)} />
        </Modal>
      </div>
    </div>
  );
}
`,
  },
  'AuthForm.tsx': {
    language: 'typescript',
    content: `import { useState } from 'react';
import { supabase } from '../lib/supabase';
import { useForm } from '../hooks/useForm';
import { Button } from './Button';
import { Input } from './Input';

interface AuthFormProps {
  onForgotPassword: () => void;
}

export function AuthForm({ onForgotPassword }: AuthFormProps) {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const { values, handleChange, validate, errors } = useForm({
    email: '',
    password: '',
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setIsLoading(true);
    setError(null);

    try {
      if (mode === 'signin') {
        const { error } = await supabase.auth.signInWithPassword({
          email: values.email,
          password: values.password,
        });
        if (error) throw error;
      } else {
        const { error } = await supabase.auth.signUp({
          email: values.email,
          password: values.password,
        });
        if (error) throw error;
      }
    } catch (err: any) {
      setError(err.message ?? 'An unexpected error occurred.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <Input
        id="email"
        type="email"
        label="Email address"
        aria-label="Email address"
        value={values.email}
        onChange={handleChange('email')}
        error={errors.email}
        placeholder="you@example.com"
        autoComplete="email"
      />
      <Input
        id="password"
        type="password"
        label="Password"
        aria-label="Password"
        value={values.password}
        onChange={handleChange('password')}
        error={errors.password}
        placeholder="••••••••"
        autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
      />
      {error && (
        <p className="text-sm text-red-400 bg-red-400/10 rounded px-3 py-2">{error}</p>
      )}
      <Button type="submit" loading={isLoading} className="w-full">
        {mode === 'signin' ? 'Sign in' : 'Create account'}
      </Button>
      <div className="flex items-center justify-between text-sm text-slate-400">
        <button
          type="button"
          onClick={() => setMode(mode === 'signin' ? 'signup' : 'signin')}
          className="hover:text-slate-200 transition-colors"
        >
          {mode === 'signin' ? 'Need an account? Sign up' : 'Already have an account?'}
        </button>
        {mode === 'signin' && (
          <button
            type="button"
            onClick={onForgotPassword}
            className="hover:text-slate-200 transition-colors"
          >
            Forgot password?
          </button>
        )}
      </div>
    </form>
  );
}
`,
  },
  'index.css': {
    language: 'css',
    content: `@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --color-bg-primary: theme('colors.slate.950');
    --color-bg-secondary: theme('colors.slate.900');
    --color-bg-elevated: theme('colors.slate.800');
    --color-text-primary: theme('colors.slate.100');
    --color-text-secondary: theme('colors.slate.400');
    --color-border: theme('colors.slate.800');
    --color-accent: theme('colors.sky.500');
  }

  body {
    @apply bg-slate-950 text-slate-100 font-sans antialiased;
  }

  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { @apply bg-slate-900; }
  ::-webkit-scrollbar-thumb { @apply bg-slate-700 rounded-full; }
  ::-webkit-scrollbar-thumb:hover { @apply bg-slate-600; }
}
`,
  },
  'Modal.tsx': {
    language: 'typescript',
    content: `import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}

export function Modal({ open, onClose, title, children }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (open) {
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-md mx-4">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 className="text-base font-semibold text-slate-100">{title}</h2>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}
`,
  },
};
