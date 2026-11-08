// Preserve form object references and edits made while a save was in flight.
export function mergeSaved(target, saved, before) {
  const object = v => v && typeof v === 'object' && !Array.isArray(v);
  for (const [key, value] of Object.entries(saved)) {
    if (object(target[key]) && object(value) && object(before[key])) {
      mergeSaved(target[key], value, before[key]);
    } else if (JSON.stringify(target[key]) === JSON.stringify(before[key])) {
      target[key] = structuredClone(value);
    }
  }
}
