/* One in-flight save. Changes made during a request are drained immediately afterward. */
export function drainChanges(state, saveOne) {
  if (state.saving) return state.saving;
  if (!state.dirty) return Promise.resolve();
  state.saving = Promise.resolve()
    .then(async () => {
      while (state.dirty) await saveOne();
    })
    .finally(() => {
      state.saving = null;
    });
  return state.saving;
}
