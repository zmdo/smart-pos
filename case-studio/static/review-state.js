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

export function previewPrerequisite(member, section) {
  if (section === 'table' || !member.photos?.length || member.privacy?.enabled === false || member.privacy?.status === 'ready') return '';
  return member.privacy?.status === 'needs_review'
    ? '头部检查尚有未通过的照片，请在会员基础信息查看原因并重新检查。'
    : '请先在会员基础信息点击「准备头部遮挡」，完成后再更新展示效果。';
}
