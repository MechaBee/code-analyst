'use client';

import CodeMirror from '@uiw/react-codemirror';
import { githubLightInit } from '@uiw/codemirror-theme-github';
import { css } from '@codemirror/lang-css';
import { html } from '@codemirror/lang-html';
import { java } from '@codemirror/lang-java';
import { javascript } from '@codemirror/lang-javascript';
import { markdown } from '@codemirror/lang-markdown';
import { python } from '@codemirror/lang-python';
import { StreamLanguage } from '@codemirror/language';
import { RangeSetBuilder, StateField, type EditorState, type Extension } from '@codemirror/state';
import { GutterMarker, Decoration, EditorView, gutter, type DecorationSet } from '@codemirror/view';
import { shell as shellMode } from '@codemirror/legacy-modes/mode/shell';
import type { CitationPreviewResponse } from '@/types/api';
import { resolveCodeLanguageFromPath } from '@/lib/codeLanguages';

export interface SourceCodePreviewProps {
  preview: CitationPreviewResponse;
}

const shell = StreamLanguage.define(shellMode);

const languageExtensions: Record<string, Extension> = {
  javascript: javascript(),
  jsx: javascript({ jsx: true }),
  typescript: javascript({ typescript: true }),
  tsx: javascript({ typescript: true, jsx: true }),
  python: python(),
  shell,
  java: java(),
  html: html(),
  css: css(),
  markdown: markdown(),
};

const sourcePreviewTheme = githubLightInit({
  settings: {
    background: '#fffaf1',
    gutterBackground: '#fffaf1',
    gutterForeground: '#66706a',
    selection: '#d9ecee',
    selectionMatch: '#d9ecee',
  },
});

const sourcePreviewEditorTheme = EditorView.theme(
  {
    '&': {
      backgroundColor: '#fffaf1',
      color: '#1e241f',
      fontSize: '13px',
    },
    '&.cm-focused': {
      outline: 'none',
    },
    '.cm-scroller': {
      overflow: 'auto',
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      lineHeight: '1.7',
    },
    '.cm-content': {
      padding: '10px 0',
    },
    '.cm-line': {
      padding: '0 16px 0 0',
    },
    '.cm-gutters': {
      borderRight: '1px solid #d9d1c4',
    },
    '.cm-source-preview-gutter .cm-gutterElement': {
      padding: '0 12px 0 16px',
    },
    '.cm-source-preview-gutter-cell': {
      color: '#66706a',
    },
    '.cm-source-preview-gutter-highlighted': {
      backgroundColor: 'rgba(19, 93, 102, 0.1)',
    },
    '.source-preview-line-number': {
      display: 'block',
      minWidth: '40px',
      textAlign: 'right',
      fontSize: '12px',
      lineHeight: '1.7',
    },
    '.cm-source-preview-highlighted': {
      backgroundColor: 'rgba(19, 93, 102, 0.1)',
    },
  },
  { dark: false }
);

export default function SourceCodePreview({ preview }: SourceCodePreviewProps) {
  const language = resolveCodeLanguageFromPath(preview.path);
  const lineNumbers = preview.lines.map((line) => line.line_number);
  const highlightedLines = new Set(
    lineNumbers.filter(
      (lineNumber) =>
        lineNumber >= preview.requested_start_line && lineNumber <= preview.requested_end_line
    )
  );

  const extensions: Extension[] = [
    buildLineHighlightField(lineNumbers, highlightedLines),
    buildLineNumberGutter(lineNumbers, highlightedLines),
    sourcePreviewEditorTheme,
  ];

  const languageExtension = language ? languageExtensions[language.id] : null;
  if (languageExtension) {
    extensions.push(languageExtension);
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-panel">
      <div className="flex items-center justify-between gap-3 border-b border-line bg-panel px-4 py-2 text-xs text-muted">
        <span>
          Preview window {preview.preview_start_line}-{preview.preview_end_line}
        </span>
        <span className="rounded-full border border-line/80 bg-cream px-2 py-0.5 font-medium text-ink">
          {language?.label ?? 'Plain text'}
        </span>
      </div>
      <CodeMirror
        key={`${preview.snapshot_id}:${preview.path}:${preview.preview_start_line}:${preview.preview_end_line}`}
        value={preview.lines.map((line) => line.content).join('\n')}
        theme={sourcePreviewTheme}
        extensions={extensions}
        basicSetup={false}
        editable={false}
        readOnly
      />
    </div>
  );
}

class PreviewLineNumberMarker extends GutterMarker {
  readonly elementClass: string;

  constructor(
    private readonly label: string,
    highlighted: boolean,
    private readonly includeTestId: boolean
  ) {
    super();
    this.elementClass = highlighted
      ? 'cm-source-preview-gutter-cell cm-source-preview-gutter-highlighted'
      : 'cm-source-preview-gutter-cell';
  }

  eq(other: GutterMarker): boolean {
    return (
      other instanceof PreviewLineNumberMarker &&
      other.label === this.label &&
      other.elementClass === this.elementClass &&
      other.includeTestId === this.includeTestId
    );
  }

  toDOM() {
    const element = document.createElement('span');
    element.className = 'source-preview-line-number';
    element.textContent = this.label;
    if (this.includeTestId) {
      element.dataset.testid = 'citation-preview-line-number';
    }
    return element;
  }
}

function buildLineNumberGutter(lineNumbers: number[], highlightedLines: Set<number>): Extension {
  const spacerLabel = String(
    lineNumbers.reduce((max, lineNumber) => Math.max(max, lineNumber), 0)
  );

  return gutter({
    class: 'cm-source-preview-gutter',
    lineMarker(view, line) {
      const documentLineNumber = view.state.doc.lineAt(line.from).number;
      const absoluteLineNumber = lineNumbers[documentLineNumber - 1] ?? documentLineNumber;
      return new PreviewLineNumberMarker(
        String(absoluteLineNumber),
        highlightedLines.has(absoluteLineNumber),
        true
      );
    },
    initialSpacer() {
      return new PreviewLineNumberMarker(spacerLabel, false, false);
    },
  });
}

function buildLineHighlightField(lineNumbers: number[], highlightedLines: Set<number>): Extension {
  return StateField.define<DecorationSet>({
    create(state) {
      return buildLineHighlightDecorations(state, lineNumbers, highlightedLines);
    },
    update(decorations, transaction) {
      if (!transaction.docChanged) {
        return decorations;
      }

      return buildLineHighlightDecorations(transaction.state, lineNumbers, highlightedLines);
    },
    provide: (field) => EditorView.decorations.from(field),
  });
}

function buildLineHighlightDecorations(
  state: EditorState,
  lineNumbers: number[],
  highlightedLines: Set<number>
): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();

  for (let documentLineNumber = 1; documentLineNumber <= state.doc.lines; documentLineNumber += 1) {
    const absoluteLineNumber = lineNumbers[documentLineNumber - 1] ?? documentLineNumber;
    if (!highlightedLines.has(absoluteLineNumber)) {
      continue;
    }

    builder.add(
      state.doc.line(documentLineNumber).from,
      state.doc.line(documentLineNumber).from,
      Decoration.line({
        attributes: {
          class: 'cm-source-preview-highlighted',
          'data-testid': 'citation-preview-highlighted-line',
        },
      })
    );
  }

  return builder.finish();
}
