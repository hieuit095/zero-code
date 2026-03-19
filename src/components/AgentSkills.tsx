/**
 * ==========================================
 * Author: Hieu Nguyen - Codev Team
 * Email: hieuit095@gmail.com
 * Project: ZeroCode - Autonomous Multi-Agent IDE
 * ==========================================
 */
// @ai-module: Agent Skills
// @ai-role: Pure local-state UI panel for browsing and toggling agent capability "skills".
//           All state is local (useState) — no store dependency. Skills data is a local constant.
//           This is currently UI-only scaffolding; skill toggles do not affect actual agent behavior.
// @ai-dependencies: types/index.ts (AgentRole — for filtering)

// [AI-STRICT] Skill toggle state is local — it does NOT propagate to any store or backend.
//             When the real backend is connected, move skill definitions and enabled state into a
//             dedicated store (e.g., skillStore) and wire toggles to a WebSocket skill:toggle event.
// @ai-integration-point: The "Add skill" button is a no-op placeholder. When implementing custom skills,
//   wire it to open a form that calls the backend skill registration API.


import { useState } from 'react';
import {
  Zap,
  Globe,
  GitBranch,
  Terminal,
  FileSearch,
  Shield,
  Code2,
  TestTube2,
  Search,
  Plus,
  ToggleLeft,
  ToggleRight,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import type { AgentRole } from '../types';

type SkillCategory = 'all' | AgentRole;

interface Skill {
  id: string;
  name: string;
  description: string;
  agent: AgentRole;
  enabled: boolean;
  icon: React.ReactNode;
  category: string;
}

const initialSkills: Skill[] = [
  {
    id: 's1',
    name: 'Web Browsing',
    description: 'Browse URLs, fetch documentation, and extract web content for research.',
    agent: 'tech-lead',
    enabled: true,
    icon: <Globe className="w-3.5 h-3.5" />,
    category: 'Research',
  },
  {
    id: 's2',
    name: 'Git Operations',
    description: 'Read commit history, create branches, and inspect diffs.',
    agent: 'tech-lead',
    enabled: true,
    icon: <GitBranch className="w-3.5 h-3.5" />,
    category: 'Version Control',
  },
  {
    id: 's3',
    name: 'Code Generation',
    description: 'Write and edit source files across TypeScript, CSS, and config formats.',
    agent: 'dev',
    enabled: true,
    icon: <Code2 className="w-3.5 h-3.5" />,
    category: 'Coding',
  },
  {
    id: 's4',
    name: 'Terminal Execution',
    description: 'Run shell commands, build scripts, and package installs in a sandboxed environment.',
    agent: 'dev',
    enabled: true,
    icon: <Terminal className="w-3.5 h-3.5" />,
    category: 'Execution',
  },
  {
    id: 's5',
    name: 'File Search',
    description: 'Search across the codebase with regex patterns and file-type filters.',
    agent: 'dev',
    enabled: true,
    icon: <FileSearch className="w-3.5 h-3.5" />,
    category: 'Coding',
  },
  {
    id: 's6',
    name: 'Test Runner',
    description: 'Execute unit, integration, and e2e test suites and parse results.',
    agent: 'qa',
    enabled: true,
    icon: <TestTube2 className="w-3.5 h-3.5" />,
    category: 'Testing',
  },
  {
    id: 's7',
    name: 'Static Analysis',
    description: 'Run ESLint, TypeScript compiler, and accessibility audits against source files.',
    agent: 'qa',
    enabled: true,
    icon: <Search className="w-3.5 h-3.5" />,
    category: 'Testing',
  },
  {
    id: 's8',
    name: 'Security Scan',
    description: 'Audit dependencies for CVEs and scan code for OWASP vulnerabilities.',
    agent: 'qa',
    enabled: false,
    icon: <Shield className="w-3.5 h-3.5" />,
    category: 'Security',
  },
];

const agentConfig: Record<AgentRole, { label: string; color: string; bg: string; border: string; dot: string }> = {
  'tech-lead': {
    label: 'Tech Lead',
    color: 'text-amber-300',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/25',
    dot: 'bg-amber-400',
  },
  dev: {
    label: 'Dev',
    color: 'text-sky-300',
    bg: 'bg-sky-500/10',
    border: 'border-sky-500/25',
    dot: 'bg-sky-400',
  },
  qa: {
    label: 'QA',
    color: 'text-emerald-300',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/25',
    dot: 'bg-emerald-400',
  },
};

const filterTabs: { key: SkillCategory; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'tech-lead', label: 'Lead' },
  { key: 'dev', label: 'Dev' },
  { key: 'qa', label: 'QA' },
];

function groupByCategory(skills: Skill[]): Record<string, Skill[]> {
  return skills.reduce<Record<string, Skill[]>>((acc, s) => {
    (acc[s.category] ??= []).push(s);
    return acc;
  }, {});
}

interface SkillRowProps {
  skill: Skill;
  onToggle: (id: string) => void;
}

function SkillRow({ skill, onToggle }: SkillRowProps) {
  const cfg = agentConfig[skill.agent];
  return (
    <div className={`group flex items-start gap-2.5 px-2.5 py-2 rounded-md transition-colors ${skill.enabled ? 'hover:bg-slate-800/60' : 'hover:bg-slate-800/30 opacity-50'}`}>
      <div className={`mt-0.5 shrink-0 flex items-center justify-center w-6 h-6 rounded-md ${cfg.bg} border ${cfg.border} ${cfg.color}`}>
        {skill.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-0.5">
          <span className={`text-[12px] font-medium ${skill.enabled ? 'text-slate-200' : 'text-slate-500'}`}>
            {skill.name}
          </span>
          <span className={`text-[9px] font-semibold px-1 py-0.5 rounded border ${cfg.bg} ${cfg.border} ${cfg.color} uppercase tracking-wide`}>
            {cfg.label}
          </span>
        </div>
        <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-2">
          {skill.description}
        </p>
      </div>
      <button
        onClick={() => onToggle(skill.id)}
        className="mt-0.5 shrink-0 text-slate-500 hover:text-slate-300 transition-colors"
        title={skill.enabled ? 'Disable skill' : 'Enable skill'}
      >
        {skill.enabled
          ? <ToggleRight className="w-4.5 h-4.5 text-sky-400 w-[18px] h-[18px]" />
          : <ToggleLeft className="w-[18px] h-[18px]" />
        }
      </button>
    </div>
  );
}

interface CategoryGroupProps {
  category: string;
  skills: Skill[];
  onToggle: (id: string) => void;
}

function CategoryGroup({ category, skills, onToggle }: CategoryGroupProps) {
  const [open, setOpen] = useState(true);
  const enabledCount = skills.filter((s) => s.enabled).length;

  return (
    <div className="mb-1">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1.5 w-full px-2.5 py-1 text-[10px] font-semibold text-slate-500 uppercase tracking-widest hover:text-slate-400 transition-colors"
      >
        {open ? <ChevronDown className="w-2.5 h-2.5" /> : <ChevronRight className="w-2.5 h-2.5" />}
        {category}
        <span className="ml-auto text-[9px] font-normal normal-case tracking-normal text-slate-600">
          {enabledCount}/{skills.length}
        </span>
      </button>
      {open && skills.map((s) => (
        <SkillRow key={s.id} skill={s} onToggle={onToggle} />
      ))}
    </div>
  );
}

export function AgentSkills() {
  const [skills, setSkills] = useState<Skill[]>(initialSkills);
  const [filter, setFilter] = useState<SkillCategory>('all');
  const [search, setSearch] = useState('');

  const toggleSkill = (id: string) => {
    setSkills((prev) =>
      prev.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s))
    );
  };

  const filtered = skills.filter((s) => {
    const matchesFilter = filter === 'all' || s.agent === filter;
    const matchesSearch =
      !search ||
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      s.description.toLowerCase().includes(search.toLowerCase());
    return matchesFilter && matchesSearch;
  });

  const grouped = groupByCategory(filtered);
  const enabledTotal = skills.filter((s) => s.enabled).length;

  return (
    <div className="flex flex-col h-full">
      <div className="px-2.5 py-2 border-b border-slate-800 shrink-0 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Zap className="w-3 h-3 text-sky-400" />
            <span className="text-[11px] font-semibold text-slate-300">
              {enabledTotal}
              <span className="text-slate-500 font-normal">/{skills.length} active</span>
            </span>
          </div>
          <button className="flex items-center gap-1 px-2 py-1 rounded-md bg-sky-500/10 border border-sky-500/20 text-sky-400 hover:bg-sky-500/20 transition-colors">
            <Plus className="w-2.5 h-2.5" />
            <span className="text-[10px] font-medium">Add skill</span>
          </button>
        </div>

        <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-900 border border-slate-700 focus-within:border-sky-500/50 transition-colors">
          <Search className="w-3 h-3 text-slate-500 shrink-0" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search skills..."
            className="flex-1 bg-transparent text-[11px] text-slate-300 placeholder:text-slate-600 focus:outline-none"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="text-slate-500 hover:text-slate-300 text-[10px] transition-colors"
            >
              ✕
            </button>
          )}
        </div>

        <div className="flex items-center gap-1">
          {filterTabs.map((tab) => {
            const count = tab.key === 'all'
              ? skills.length
              : skills.filter((s) => s.agent === tab.key).length;
            return (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key)}
                className={`flex-1 py-1 rounded text-[10px] font-medium transition-colors ${
                  filter === tab.key
                    ? 'bg-sky-500/15 text-sky-300 border border-sky-500/30'
                    : 'text-slate-500 hover:text-slate-300 border border-transparent hover:border-slate-700'
                }`}
              >
                {tab.label}
                <span className={`ml-0.5 ${filter === tab.key ? 'text-sky-400' : 'text-slate-600'}`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {Object.keys(grouped).length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-600">
            <Search className="w-6 h-6" />
            <span className="text-xs">No skills match your search</span>
          </div>
        ) : (
          Object.entries(grouped).map(([category, categorySkills]) => (
            <CategoryGroup
              key={category}
              category={category}
              skills={categorySkills}
              onToggle={toggleSkill}
            />
          ))
        )}
      </div>
    </div>
  );
}
