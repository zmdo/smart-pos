export function movedPosition(panel, face, dx, dy) {
  const [w,h] = panel.size, [sw,sh] = face.sticker_size;
  const origin = face.manual_position || [face.default_rect[0]/w, face.default_rect[1]/h];
  const minY = Math.min(0,face.default_rect[1]/h);
  return [Math.max(0,Math.min(1-sw/w,origin[0]+dx)), Math.max(minY,Math.min(1-sh/h,origin[1]+dy))];
}
export function stickerRect(panel, face) {
  const [w,h] = panel.size, [sw,sh] = face.sticker_size;
  const position = face.manual_position || [face.default_rect[0]/w,face.default_rect[1]/h];
  const x=Math.round(position[0]*w), y=Math.round(position[1]*h);
  return [x,y,sw,sh];
}
export function editorEdits(groups) {
  return groups.flatMap(g=>g.panels.flatMap(p=>p.faces.map(f=>({scope:g.scope,asset_id:p.asset_id,
    face:f.source_face,position:f.manual_position ? [...f.manual_position] : null,deleted:f.deleted}))));
}
