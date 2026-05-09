1. **Optimize `FileRow` with `React.memo` and Custom Comparison**
   - Use `replace_with_git_merge_diff` on `src/components/FileExplorer.tsx` to wrap `FileRow` in `React.memo()`.
   - Update `FileRow` to use a named inner function (e.g., `FileRowImpl` or arrow function) to avoid shadowing issues.
   - Provide a custom `arePropsEqual` function for `memo`.
   - The comparison should check if the node is a folder (`prevProps.node.type === 'folder'`). If it is, return `false` (always re-render folders to propagate props down).
   - Otherwise, for file nodes, compare their specific selection state (`isSelected`). If it didn't change, return `true` to prevent re-rendering.
2. **Optimize `onSelect` callback in `FileExplorer`**
   - Use `replace_with_git_merge_diff` on `src/components/FileExplorer.tsx` to extract the `onSelect` anonymous arrow function `(id, _name) => fetchAndOpenFile(id, workspaceId)` into a `useCallback` hook named `handleSelect`.
   - Add `useCallback` to the import from `'react'`.
   - Update `FileRow` usage in `FileExplorer` to use `onSelect={handleSelect}`.
3. **Verify Code Changes**
   - Use `cat src/components/FileExplorer.tsx` to confirm that the changes were written accurately.
4. **Update `.jules/bolt.md`**
   - Use `run_in_bash_session` to append a new entry to `.jules/bolt.md` explaining the recursive tree memoization pattern to prevent O(N) re-renders on file selection changes.
5. **Verify with Tests**
   - Run `pnpm lint`, `pnpm typecheck`, and `pnpm test` (even if empty) to verify that the code compiles and follows linting rules.
6. **Complete pre commit steps**
   - Complete pre commit steps to ensure proper testing, verification, review, and reflection are done.
7. **Submit PR**
   - Create a PR with title "⚡ Bolt: [performance improvement] O(1) FileTree Selection Re-renders".
