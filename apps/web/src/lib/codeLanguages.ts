export interface CodeLanguageSpec {
  id: string;
  label: string;
}

const javascript: CodeLanguageSpec = { id: 'javascript', label: 'JavaScript' };
const jsx: CodeLanguageSpec = { id: 'jsx', label: 'JSX' };
const typescript: CodeLanguageSpec = { id: 'typescript', label: 'TypeScript' };
const tsx: CodeLanguageSpec = { id: 'tsx', label: 'TSX' };
const python: CodeLanguageSpec = { id: 'python', label: 'Python' };
const shell: CodeLanguageSpec = { id: 'shell', label: 'Shell' };
const java: CodeLanguageSpec = { id: 'java', label: 'Java' };
const html: CodeLanguageSpec = { id: 'html', label: 'HTML' };
const css: CodeLanguageSpec = { id: 'css', label: 'CSS' };
const markdown: CodeLanguageSpec = { id: 'markdown', label: 'Markdown' };
const LANGUAGE_BY_EXTENSION = new Map<string, CodeLanguageSpec>([
  ['js', javascript],
  ['mjs', javascript],
  ['cjs', javascript],
  ['jsx', jsx],
  ['ts', typescript],
  ['mts', typescript],
  ['cts', typescript],
  ['tsx', tsx],
  ['py', python],
  ['sh', shell],
  ['bash', shell],
  ['zsh', shell],
  ['fish', shell],
  ['java', java],
  ['html', html],
  ['htm', html],
  ['xhtml', html],
  ['css', css],
  ['scss', css],
  ['sass', css],
  ['less', css],
  ['md', markdown],
  ['markdown', markdown],
  ['mdx', markdown],
]);

const LANGUAGE_BY_BASENAME = new Map<string, CodeLanguageSpec>([
  ['.bashrc', shell],
  ['.bash_profile', shell],
  ['.zshrc', shell],
  ['.zprofile', shell],
  ['.profile', shell],
  ['makefile', shell],
]);

export function resolveCodeLanguageFromPath(path: string | null | undefined): CodeLanguageSpec | null {
  if (!path) {
    return null;
  }

  const normalizedPath = path.trim().toLowerCase();
  if (!normalizedPath) {
    return null;
  }

  const segments = normalizedPath.split('/');
  const basename = segments[segments.length - 1] ?? normalizedPath;

  const basenameMatch = LANGUAGE_BY_BASENAME.get(basename);
  if (basenameMatch) {
    return basenameMatch;
  }

  const extension = basename.includes('.') ? basename.split('.').pop() : null;
  if (!extension) {
    return null;
  }

  return LANGUAGE_BY_EXTENSION.get(extension) ?? null;
}
